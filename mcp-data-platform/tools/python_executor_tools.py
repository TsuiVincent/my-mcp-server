"""
Python代码执行工具（真子进程沙箱）

工具列表：
- python_check_syntax: 检查Python代码语法
- python_exec_safe: 安全执行Python代码片段
- python_exec_json: 执行Python代码并返回JSON格式结果

底层执行统一由 sandbox_runner 提供：
- 真子进程隔离（代码崩溃/死循环不影响 MCP 服务进程）
- 资源限制 + 可 kill 的超时控制
- 模块白名单（放行 pandas/numpy/scipy/matplotlib 等科学计算栈，
  封死 os/sys/socket/subprocess 等逃逸面）
- 文件读写限定在「用户会话工作目录」内，目录跨调用保留，
  支持在同一会话中二次读取上一步产物
"""

import ast
import base64
import logging
import os
import sys

# 保证以 tools.xxx 形式导入时也能找到项目根目录下的 sandbox_runner
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sandbox_runner import (
    DEFAULT_TIMEOUT,
    MAX_TIMEOUT,
    execute as _sandbox_execute,
)

logger = logging.getLogger(__name__)

# 注册时注入的数据根目录（会话工作目录挂在其下）
_BASE_DIR = None

# 图片类产物内联回传：平台据 base64_data 托管为下载链接并在对话中内联渲染。
# 仅图片扩展名且单文件不超过 _MAX_INLINE_B64 才内联，其余保持原有 name/size/path 结构。
_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg')
_MAX_INLINE_B64 = 5 * 1024 * 1024


def _attach_image_payloads(files: list) -> list:
    """为图片类产物补充 filename 与 base64_data（供平台自动托管）。

    读取失败或体积超限时跳过该文件，不影响 files 其余字段。
    """
    for f in files or []:
        if not isinstance(f, dict):
            continue
        name = f.get('name') or ''
        if os.path.splitext(name)[1].lower() not in _IMAGE_EXTS:
            continue
        size = f.get('size') or 0
        path = f.get('path')
        if not path or size <= 0 or size > _MAX_INLINE_B64:
            continue
        try:
            with open(path, 'rb') as fp:
                data = fp.read()
        except OSError as e:
            logger.warning(f"读取图片产物失败，跳过内联: {path}: {e}")
            continue
        f['filename'] = os.path.basename(name)
        f['base64_data'] = base64.b64encode(data).decode('ascii')
    return files


def _default_base_dir() -> str:
    """未显式注入 base_dir 时的兜底目录（与 server.py 保持一致）。"""
    if os.name == "nt":
        base = os.path.join(os.path.expanduser("~"), "mcp-user-data")
    else:
        base = "/data/mcp-user-data"
    return base


def _session_workdir(base_dir: str, user_id: str) -> str:
    """获取（并创建）某用户的会话工作目录。

    目录名做字符白名单清洗，避免 user_id 中的路径分隔符造成越权。
    """
    safe_uid = "".join(
        c for c in str(user_id or "default") if c.isalnum() or c in ("-", "_")
    ) or "default"
    workdir = os.path.join(base_dir, "sandbox", safe_uid)
    os.makedirs(workdir, exist_ok=True)
    return workdir


def _check_syntax(code: str) -> dict:
    """检查Python代码语法"""
    try:
        ast.parse(code)
        return {"valid": True, "message": "语法检查通过"}
    except SyntaxError as e:
        return {
            "valid": False,
            "message": f"语法错误 (行{e.lineno}, 列{e.offset}): {e.msg}",
            "line": e.lineno,
            "offset": e.offset,
        }


def _execute(code: str, user_id: str = "default", timeout: int = DEFAULT_TIMEOUT) -> dict:
    """在真子进程沙箱中执行代码，返回统一结构。

    返回：{"success", "stdout", "stderr", "files", "execution_time_ms"}
    """
    base_dir = _BASE_DIR or _default_base_dir()
    try:
        workdir = _session_workdir(base_dir, user_id)
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"会话工作目录创建失败: {type(e).__name__}: {e}",
            "files": [],
            "execution_time_ms": 0,
        }
    return _sandbox_execute(code, workdir=workdir, timeout=timeout)


# ===================== 注册函数 =====================

def register_python_executor_tools(mcp, base_dir: str = None):
    """注册Python代码执行工具到 MCP 服务器

    Args:
        mcp: FastMCP 实例
        base_dir: 用户数据根目录；会话工作目录位于 {base_dir}/sandbox/{user_id}
    """
    global _BASE_DIR
    _BASE_DIR = base_dir or _default_base_dir()
    try:
        os.makedirs(os.path.join(_BASE_DIR, "sandbox"), exist_ok=True)
    except Exception as e:
        logger.warning("创建沙箱会话目录失败: %s", e)

    @mcp.tool(
        name="python_check_syntax",
        description="检查Python代码语法是否正确。Args: code(Python代码,必填)"
    )
    def python_check_syntax(code: str) -> str:
        result = _check_syntax(code)
        if result["valid"]:
            return "Python语法检查通过"
        return f"语法错误: {result['message']}"

    @mcp.tool(
        name="python_exec_safe",
        description=(
            "在真子进程沙箱中执行Python代码片段，支持 pandas/numpy/scipy/matplotlib "
            "等数据分析与科学计算库。文件读写限定在当前用户会话工作目录内，"
            "相对路径写的文件会在后续调用中保留。"
            "Args: code(Python代码,必填), timeout(超时秒数,默认30,最大300), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def python_exec_safe(code: str, timeout: int = DEFAULT_TIMEOUT,
                         user_id: str = "default") -> str:
        timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))

        exec_result = _execute(code, user_id=user_id, timeout=timeout)
        output_parts = []

        if exec_result["stdout"]:
            output_parts.append(f"--- 输出 ---\n{exec_result['stdout']}")

        if exec_result["stderr"]:
            output_parts.append(f"--- 错误 ---\n{exec_result['stderr']}")

        files = exec_result.get("files") or []
        if files:
            output_parts.append("--- 生成文件 ---")
            for f in files:
                output_parts.append(f"  {f['name']} ({f['size']} 字节)")

        if not output_parts:
            output_parts.append("代码执行完成（无输出）")

        output_parts.append(f"\n执行耗时: {exec_result['execution_time_ms']}ms")
        return "\n".join(output_parts)

    @mcp.tool(
        name="python_exec_json",
        description=(
            "在真子进程沙箱中执行Python代码并返回结构化JSON结果(适合程序化调用)。"
            "返回字段: success/stdout/stderr/files/execution_time_ms。"
            "沙箱内用 matplotlib 保存的 png/jpg/webp 等图片会以 filename+base64_data "
            "内联在 files 中，平台自动托管为下载链接并在对话中内联渲染。"
            "Args: code(Python代码,必填), timeout(超时秒数,默认30,最大300), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def python_exec_json(code: str, timeout: int = DEFAULT_TIMEOUT,
                         user_id: str = "default") -> dict:
        timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
        exec_result = _execute(code, user_id=user_id, timeout=timeout)
        # 图片类产物内联 base64，供平台托管为可下载链接并在对话中内联渲染
        files = _attach_image_payloads(exec_result.get("files", []))
        # 兼容旧字段（result/blocked），新增 files 结构化文件列表
        return {
            "success": exec_result["success"],
            "stdout": exec_result["stdout"],
            "stderr": exec_result["stderr"],
            "result": exec_result["stdout"],
            "blocked": False,
            "files": files,
            "execution_time_ms": exec_result["execution_time_ms"],
        }

    logger.info("Python代码执行工具已注册（真子进程沙箱）")
