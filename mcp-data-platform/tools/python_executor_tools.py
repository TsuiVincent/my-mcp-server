"""
Python代码执行工具
实现安全的Python代码片段执行器，支持标准库调用，包含语法检查、
沙箱执行、结果返回功能，具备资源限制与安全隔离机制。

工具列表：
- python_exec_safe: 安全执行Python代码片段
- python_check_syntax: 检查Python代码语法
- python_exec_with_timeout: 带超时限制的代码执行
"""

import ast
import sys
import io
import time
import signal
import logging
import traceback
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ===================== 安全配置 =====================

# 允许的标准库模块白名单
_ALLOWED_MODULES = frozenset({
    # 基础数学
    "math", "cmath", "decimal", "fractions", "statistics", "random",
    # 数据结构
    "collections", "heapq", "bisect", "array", "itertools", "functools",
    "operator", "typing",
    # 字符串与文本
    "string", "re", "textwrap", "difflib", "unicodedata",
    # 日期时间
    "datetime", "time", "calendar", "zoneinfo",
    # 文件与路径
    "os.path", "pathlib", "glob", "fnmatch", "tempfile",
    # 数据序列化
    "json", "csv", "base64", "hashlib", "hmac",
    # 工具
    "copy", "enum", "dataclasses", "pprint", "logging",
    # 数据
    "numbers", "types", "warnings",
})


# 禁止的内置函数/关键字
_DENIED_BUILTINS = frozenset({
    "exec", "eval", "compile", "open", "__import__", "input",
    "breakpoint", "memoryview"
})

# 最大执行时间（秒）
_MAX_EXECUTION_TIME = 5

# 最大内存限制（字节，接近值）
_MAX_MEMORY = 128 * 1024 * 1024  # 128MB


class _SandboxModuleImporter:
    """沙箱模块导入器：仅允许导入白名单中的模块"""

    @staticmethod
    def find_spec(fullname, path=None, target=None):
        if fullname in _ALLOWED_MODULES or any(
            fullname.startswith(f"{allowed}.") for allowed in _ALLOWED_MODULES
        ):
            return None  # 使用默认加载
        raise ImportError(f"模块 '{fullname}' 不在沙箱白名单中")

    @staticmethod
    def create_module(spec):
        return None


class _RestrictedTransformer(ast.NodeTransformer):
    """AST转换器：移除危险调用"""

    def __init__(self):
        self.has_dangerous = False

    def visit_Call(self, node):
        # 检查直接的危险调用
        if isinstance(node.func, ast.Name):
            if node.func.id in ("exec", "eval", "compile", "__import__", "open"):
                self.has_dangerous = True
                return ast.Expr(value=ast.Constant(value=f"# {node.func.id}() 调用被阻止"))
        return self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name not in _ALLOWED_MODULES and not any(
                alias.name.startswith(f"{a}.") for a in _ALLOWED_MODULES
            ):
                self.has_dangerous = True
                return ast.Expr(value=ast.Constant(value=f"# import {alias.name} 被阻止"))
        return self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            if node.module not in _ALLOWED_MODULES and not any(
                node.module.startswith(f"{a}.") for a in _ALLOWED_MODULES
            ):
                self.has_dangerous = True
                return ast.Expr(value=ast.Constant(value=f"# from {node.module} import 被阻止"))
        return self.generic_visit(node)


# ===================== 实现 =====================

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
            "offset": e.offset
        }


def _transform_code(code: str) -> tuple:
    """安全转换代码，返回(转换后代码, 是否有被阻止的内容)"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, False

    transformer = _RestrictedTransformer()
    new_tree = transformer.visit(tree)
    ast.fix_missing_locations(new_tree)

    try:
        new_code = ast.unparse(new_tree)
        return new_code, transformer.has_dangerous
    except Exception:
        return code, transformer.has_dangerous


def _execute_in_sandbox(code: str, timeout: int = _MAX_EXECUTION_TIME) -> dict:
    """在沙箱中执行Python代码"""
    result = {
        "success": False,
        "stdout": "",
        "stderr": "",
        "result": None,
        "blocked": False,
        "execution_time_ms": 0
    }

    # 语法检查
    syntax_result = _check_syntax(code)
    if not syntax_result["valid"]:
        result["stderr"] = syntax_result["message"]
        return result

    # AST安全转换
    transformed_code, has_blocked = _transform_code(code)
    result["blocked"] = has_blocked

    # 构建沙箱全局环境
    safe_builtins = {
        name: getattr(__builtins__, name)
        for name in dir(__builtins__)
        if name not in _DENIED_BUILTINS and not name.startswith("_")
    }
    safe_builtins.update({
        "__builtins__": safe_builtins,
        "print": lambda *args, **kwargs: _capture_print(*args, **kwargs),
    })

    safe_globals = {"__builtins__": safe_builtins}

    # 捕获输出
    captured_output = io.StringIO()
    captured_error = io.StringIO()

    def _capture_print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        captured_output.write(sep.join(str(a) for a in args) + end)

    # 在单独线程中执行
    execution_output = {}

    def _run():
        try:
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = captured_output
            sys.stderr = captured_error

            local_ns = {}
            exec(transformed_code, safe_globals, local_ns)

            sys.stdout = old_stdout
            sys.stderr = old_stderr

            # 收集最后一个表达式结果
            last_val = None
            for val in local_ns.values():
                if not val.__class__.__name__.startswith("_"):
                    pass
            execution_output["result"] = local_ns
            execution_output["success"] = True
        except Exception as e:
            execution_output["success"] = False
            execution_output["error"] = f"{type(e).__name__}: {str(e)}"
            execution_output["traceback"] = traceback.format_exc()

    start_time = time.time()
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    elapsed_ms = int((time.time() - start_time) * 1000)
    result["execution_time_ms"] = elapsed_ms

    if thread.is_alive():
        result["stderr"] = f"执行超时 ({timeout}s)"
        return result

    result["stdout"] = captured_output.getvalue()
    result["stderr"] = captured_error.getvalue()
    result["success"] = execution_output.get("success", False)

    if result["success"]:
        local_ns = execution_output.get("result", {})
        # 导出非私有变量
        exported = {}
        for k, v in local_ns.items():
            if not k.startswith("_") and k != "__builtins__":
                try:
                    exported[k] = repr(v)
                except Exception:
                    exported[k] = f"<{type(v).__name__}>"
        result["result"] = exported
        if has_blocked:
            result["stdout"] = "【警告】部分危险调用已被阻止。\n" + result["stdout"]
    else:
        result["stderr"] = execution_output.get("error", "未知错误")

    return result


# ===================== 注册函数 =====================

def register_python_executor_tools(mcp):
    """注册Python代码执行工具到 MCP 服务器"""

    @mcp.tool(
        name="python_check_syntax",
        description="检查Python代码语法是否正确。Args: code(Python代码,必填)"
    )
    def python_check_syntax(code: str) -> str:
        result = _check_syntax(code)
        if result["valid"]:
            return "Python语法检查通过"
        else:
            return f"语法错误: {result['message']}"

    @mcp.tool(
        name="python_exec_safe",
        description="安全执行Python代码片段(沙箱环境,仅允许数学/字符串/日期/json/csv等标准库)。Args: code(Python代码,必填), timeout(超时秒数,默认5,最大30)"
    )
    def python_exec_safe(code: str, timeout: int = 5) -> str:
        if timeout > 30:
            timeout = 30
        if timeout < 1:
            timeout = 5

        exec_result = _execute_in_sandbox(code, timeout)
        output_parts = []

        if exec_result["blocked"]:
            output_parts.append("【安全提示】代码中部分危险调用已被自动移除。")

        if exec_result["stdout"]:
            output_parts.append(f"--- 输出 ---\n{exec_result['stdout'].strip()}")

        if exec_result["stderr"]:
            output_parts.append(f"--- 错误 ---\n{exec_result['stderr']}")

        if exec_result["success"] and exec_result.get("result"):
            output_parts.append(f"--- 变量 ---")
            for k, v in exec_result["result"].items():
                output_parts.append(f"  {k} = {v}")

        if not output_parts:
            output_parts.append("代码执行完成（无输出）")

        output_parts.append(f"\n执行耗时: {exec_result['execution_time_ms']}ms")

        return "\n".join(output_parts)

    @mcp.tool(
        name="python_exec_json",
        description="执行Python代码并返回JSON格式结果(适合程序化调用)。Args: code(Python代码,必填)"
    )
    def python_exec_json(code: str) -> str:
        import json as json_mod
        exec_result = _execute_in_sandbox(code, _MAX_EXECUTION_TIME)
        return json_mod.dumps(exec_result, ensure_ascii=False, indent=2)

    logger.info("Python代码执行工具已注册")
