# -*- coding: utf-8 -*-
"""MCP 数据分析沙箱执行器（真子进程隔离）。

设计目标（替换 python_executor_tools 里原有的进程内 exec 伪沙箱）：
- 子进程隔离：用户代码在独立 Python 进程中执行，崩溃/死循环不影响服务主进程；
- 资源限制：POSIX 用 resource.setrlimit（内存），Windows 用监控线程兜底；
- 超时可杀：subprocess.communicate(timeout) + proc.kill()，线程模型无法做到的这里能做到；
- 导入白名单：科学计算栈（pandas/numpy/scipy/matplotlib 等）放行，os/socket/subprocess 等封死；
- 文件收敛：所有文件读写限定在「会话工作目录」内，目录跨调用保留，支持二次读取上一步产物；
- 库级 I/O 校验：pandas/numpy/matplotlib 等 C 扩展的文件读写函数（read_csv/to_csv/np.load/
  np.save/savefig 等）在 AST 层对「路径字面量」做工作目录收敛，弥补它们绕过运行时 _safe_open
  调用 libc 的缺口。已知限制：变量拼接/运行期构造的路径无法静态判定，仍需 OS 级隔离兜底；
- 中文可视化：自动注入 Agg 后端与中文字体，避免图表中文变方框。

返回结构：
    {"success": bool, "stdout": str, "stderr": str, "files": [{"name","size","path"}],
     "execution_time_ms": int}

与平台侧 backend/sandbox.py 保持同源思路，但面向「数据分析」场景：
- 放行科学计算栈（平台侧沙箱面向通用脚本，未放行）；
- 输出目录为持久会话目录而非临时目录。
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# ===================== 白名单 =====================

# 允许导入的模块根名
SAFE_MODULES = {
    # 基础标准库
    'math', 'cmath', 'decimal', 'fractions', 'statistics', 'random',
    'collections', 'heapq', 'bisect', 'array', 'itertools', 'functools',
    'operator', 'typing', 'string', 're', 'textwrap', 'difflib', 'unicodedata',
    'datetime', 'time', 'calendar', 'zoneinfo',
    'json', 'csv', 'base64', 'hashlib', 'hmac', 'uuid', 'secrets',
    'copy', 'enum', 'dataclasses', 'pprint', 'logging', 'warnings',
    'numbers', 'types', 'io', 'html', 'binascii', 'stat',
    # 数据分析科学计算栈（本次升级核心）
    'pandas', 'numpy', 'scipy', 'statsmodels', 'sklearn',
    'matplotlib', 'mpl_toolkits', 'openpyxl', 'xlrd', 'pyarrow',
    'polars', 'jinja2', 'tabulate',
    # 私有数据表全量计算通道：sqlite3.connect 受库级 I/O 白名单约束
    # （仅放行本人 user_sqlite/{uid}_private.db，见 _escapes_workdir）
    'sqlite3',
}

# 环境变量扩展（逗号分隔），便于内网按需放行更多库
_extra_raw = os.environ.get('MCP_SANDBOX_EXTRA_MODULES', '')
if _extra_raw:
    SAFE_MODULES |= {m.strip() for m in _extra_raw.split(',') if m.strip()}

# 禁止的内置函数
DANGEROUS_BUILTINS = {
    '__import__', 'eval', 'exec', 'compile', 'input', 'breakpoint',
    'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr',
    'memoryview',
}

# 禁止的 AST 节点
FORBIDDEN_AST_NODES = {
    'Exec', 'Eval', 'Global', 'Nonlocal', 'Delete', 'Raise',
    'TryStar', 'AsyncWith', 'Yield', 'YieldFrom', 'Await',
    'AsyncFor', 'AsyncFunctionDef',
}

_ALLOWED_DUNDER_ATTRS = {'__name__'}

# 库级文件 I/O 入口（由 C 扩展实现，直接调 libc，绕过运行时 _safe_open）。
# 键为函数/方法名（AST 层只能按名字匹配），值为需要校验的位置参数下标集合。
_LIB_FILE_IO_POS_ARGS = {
    # pandas 读
    'read_csv': (0,), 'read_table': (0,), 'read_fwf': (0,), 'read_excel': (0,),
    'read_json': (0,), 'read_html': (0,), 'read_xml': (0,), 'read_pickle': (0,),
    'read_parquet': (0,), 'read_feather': (0,), 'read_orc': (0,), 'read_hdf': (0,),
    'read_stata': (0,), 'read_sas': (0,), 'read_spss': (0,),
    # pandas 写
    'to_csv': (0,), 'to_excel': (0,), 'to_json': (0,), 'to_html': (0,),
    'to_xml': (0,), 'to_pickle': (0,), 'to_parquet': (0,), 'to_feather': (0,),
    'to_orc': (0,), 'to_hdf': (0,), 'to_stata': (0,), 'to_markdown': (0,),
    'to_latex': (0,),
    'ExcelWriter': (0,), 'ExcelFile': (0,), 'HDFStore': (0,),
    # numpy
    'load': (0,), 'save': (0,), 'savez': (0,), 'savez_compressed': (0,),
    'loadtxt': (0,), 'savetxt': (0,), 'fromfile': (0,), 'tofile': (0,),
    'memmap': (0,), 'genfromtxt': (0,),
    # matplotlib
    'savefig': (0,), 'imsave': (0,),
    # openpyxl / pyarrow / polars
    'load_workbook': (0,),
    'write_table': (1,),
    'scan_csv': (0,), 'scan_parquet': (0,), 'scan_ipc': (0,),
    'write_csv': (0,), 'write_parquet': (0,), 'write_ipc': (0,),
    # sqlite3 / DB-API 连接（首参为库文件路径；pymysql 等首参为主机名，
    # 相对串会按工作目录内路径判定、不会误伤）
    'connect': (0,),
}

# 上述库函数的路径参数常见关键字名
_PATH_KWARGS = {
    'filepath_or_buffer', 'path_or_buf', 'path', 'file', 'filename',
    'fname', 'filepath', 'filename_or_obj', 'buf', 'where',
}


def _static_str(node):
    """尽力静态求值字符串字面量；无法确定时返回 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_str(node.left)
        right = _static_str(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            part = _static_str(value)
            if part is None:
                return None
            parts.append(part)
        return ''.join(parts)
    return None


def _user_private_db_path(workdir: str) -> str:
    """由会话工作目录推导本人私有 SQLite 库路径。

    沙箱工作目录固定为 {base_dir}/sandbox/{uid}（见 _session_workdir），
    私有库位于 {base_dir}/user_sqlite/{uid}_private.db（与
    tools.user_kb_sqlite_tools.get_user_sqlite_path 保持一致）。
    uid 取自工作目录名（已做字符清洗），天然按用户隔离、无越权面。
    """
    wd = os.path.normpath(os.path.abspath(workdir))
    base = os.path.dirname(os.path.dirname(wd))  # 剥掉 sandbox/{uid} 两级
    uid = os.path.basename(wd)
    return os.path.normpath(os.path.join(base, 'user_sqlite', f'{uid}_private.db'))


def _escapes_workdir(path_str: str, workdir: str = None) -> bool:
    """判断字面量路径是否越出会话工作目录。

    workdir 已知时按沙箱运行时的同一规则解析；workdir 为 None 时保守判定
    （绝对路径或含 '..' 的路径一律视为越界）。
    白名单：本人私有 SQLite 库文件（路径与 user_id 精确匹配）不受工作目录限制。
    支持 file:/path?xxx URI 形式（sqlite3 uri=True）。
    """
    if not path_str:
        return False
    if path_str.startswith('file:'):
        # sqlite3 URI：file:/path?mode=ro → 取 /path 参与判定
        path_str = path_str[5:].split('?', 1)[0]
    if workdir:
        base = os.path.normpath(os.path.abspath(workdir))
        target = os.path.normpath(path_str if os.path.isabs(path_str)
                                  else os.path.join(base, path_str))
        if target == base or target.startswith(base + os.sep):
            return False
        # 白名单：本人私有数据表（pandas 全量计算/导出通道）
        try:
            if target == _user_private_db_path(workdir):
                return False
        except Exception:
            pass
        return True
    if os.path.isabs(path_str) or path_str.startswith(('/', '\\')):
        return True
    return '..' in path_str.replace('\\', '/').split('/')

# 默认超时（秒）与上限
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300


class _SandboxValidator(ast.NodeVisitor):
    """AST 预扫描：拦截危险导入、危险调用、dunder 逃逸与库级文件 I/O 越界。"""

    def __init__(self, workdir: str = None):
        self.errors = []
        self.workdir = workdir

    def visit_Import(self, node):
        for alias in node.names:
            root = alias.name.split('.')[0]
            if root not in SAFE_MODULES:
                self.errors.append(f"禁止导入模块: {root}")

    def visit_ImportFrom(self, node):
        if node.module:
            root = node.module.split('.')[0]
            if root not in SAFE_MODULES:
                self.errors.append(f"禁止导入模块: {root}")

    def _check_lib_io(self, name, node):
        """校验库级文件读写函数的路径字面量是否越出工作目录。"""
        positions = _LIB_FILE_IO_POS_ARGS.get(name)
        if not positions:
            return
        candidates = [node.args[i] for i in positions if len(node.args) > i]
        for kw in node.keywords or []:
            if kw.arg in _PATH_KWARGS:
                candidates.append(kw.value)
        for arg in candidates:
            path_str = _static_str(arg)
            if path_str is None:
                continue
            if _escapes_workdir(path_str, self.workdir):
                self.errors.append(
                    f"禁止库级文件 I/O 越界: {name}() 路径指向工作目录之外: {path_str}"
                )

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id in DANGEROUS_BUILTINS:
                self.errors.append(f"禁止调用: {node.func.id}()")
            else:
                self._check_lib_io(node.func.id, node)
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in ('system', 'popen', 'spawn', 'spawnl', 'execv', 'execve'):
                self.errors.append(f"禁止调用: .{node.func.attr}()")
            self._check_lib_io(node.func.attr, node)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.attr, str) and node.attr.startswith('__') and node.attr.endswith('__'):
            if node.attr not in _ALLOWED_DUNDER_ATTRS:
                self.errors.append(f"禁止访问: .{node.attr}")
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if isinstance(node.slice, ast.Constant):
            key = node.slice.value
            if isinstance(key, str) and key.startswith('__') and key.endswith('__'):
                if key not in _ALLOWED_DUNDER_ATTRS:
                    self.errors.append(f"禁止下标访问: ['{key}']")
        self.generic_visit(node)


def validate_code(code: str, workdir: str = None) -> tuple:
    """预扫描代码，返回 (valid, errors)。

    Args:
        code: 待校验代码
        workdir: 会话工作目录；提供时用于判定库级文件 I/O 的路径字面量是否越界，
            None 时按保守规则（绝对路径或含 '..' 即视为越界）判定
    """
    if not code or not code.strip():
        return False, ["代码为空"]
    if len(code) > 100_000:
        return False, ["代码长度超过限制 (100KB)"]
    try:
        tree = ast.parse(code, mode='exec')
    except SyntaxError as e:
        return False, [f"语法错误: 第{e.lineno}行: {e.msg}"]

    validator = _SandboxValidator(workdir)
    for node in ast.walk(tree):
        if type(node).__name__ in FORBIDDEN_AST_NODES:
            validator.errors.append(f"禁止语法: {type(node).__name__}")
    validator.visit(tree)
    return len(validator.errors) == 0, validator.errors


# ===================== 沙箱脚本构建 =====================

def _build_sandbox_script(user_code: str, workdir: str, max_memory_mb: int) -> str:
    allowed_builtins = ', '.join(f"'{b}'" for b in sorted(_safe_builtin_names()))
    allowed_modules = ', '.join(f"'{m}'" for m in sorted(SAFE_MODULES))
    workdir_json = json.dumps(workdir)

    return f'''
import sys, builtins, json as _json, os as _os

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    import resource as _resource
    _mem = {max_memory_mb} * 1024 * 1024
    _resource.setrlimit(_resource.RLIMIT_AS, (_mem, _mem))
except (ImportError, ValueError, AttributeError):
    pass

_WORKDIR = {workdir_json}
_original_import = __import__
_allowed = {{{allowed_modules}}}

def _safe_import(name, *args, **kwargs):
    root = name.split('.')[0]
    if root not in _allowed:
        raise ImportError("模块 '%s' 不在沙箱白名单中" % root)
    return _original_import(name, *args, **kwargs)

def _check_path(p):
    ap = _os.path.normpath(_os.path.join(_WORKDIR, p)) if not _os.path.isabs(p) else _os.path.normpath(p)
    base = _os.path.normpath(_WORKDIR)
    if not (ap == base or ap.startswith(base + _os.sep)):
        raise PermissionError("只允许在工作目录内操作文件: %s" % p)
    return ap

def _safe_open(file, mode='r', *args, **kwargs):
    return open(_check_path(str(file)), mode, *args, **kwargs)

_allowed_builtins = {{{allowed_builtins}}}
_sandbox_builtins = {{k: getattr(builtins, k) for k in _allowed_builtins if hasattr(builtins, k)}}
_sandbox_builtins['__import__'] = _safe_import
_sandbox_builtins['open'] = _safe_open
_sandbox_builtins['eval'] = None
_sandbox_builtins['exec'] = None
_sandbox_builtins['compile'] = None
_sandbox_builtins['input'] = None
_sandbox_builtins['breakpoint'] = None

# 可视化：无头后端 + 中文字体（在用户代码 import matplotlib 前生效）
try:
    import matplotlib
    matplotlib.use('Agg')
    matplotlib.rcParams['font.sans-serif'] = [
        'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'Microsoft YaHei',
        'SimHei', 'PingFang SC', 'DejaVu Sans',
    ]
    matplotlib.rcParams['axes.unicode_minus'] = False
except Exception:
    pass

# 单个命名空间：globals 与 locals 必须是同一 dict。若像过去那样传
# exec(code, globals, locals) 两个不同 dict，执行语义等价于「类体作用域」——
# 模块级推导式/生成器表达式只能解析 globals、看不到 locals 中的模块级名字，
# 于是 `for f in xs: any(f in n for n in names)` 会抛 NameError: name 'f' is not
# defined（知识图谱技能的中文字体检测即命中）。传一个 dict 即恢复标准模块作用域。
_ns = {{'__builtins__': _sandbox_builtins, '__name__': '__main__'}}
try:
    _code = compile({json.dumps(user_code)}, '<mcp-sandbox>', 'exec')
    exec(_code, _ns)
except SystemExit:
    pass
except Exception as e:
    import traceback as _tb
    sys.stderr.write("{{}}: {{}}\\n{{}}".format(type(e).__name__, e, _tb.format_exc()))
    sys.exit(1)
'''


def _safe_builtin_names():
    """构造安全内置函数名集合。"""
    base = {
        'True', 'False', 'None', 'abs', 'all', 'any', 'ascii', 'bin', 'bool',
        'bytearray', 'bytes', 'callable', 'chr', 'classmethod', 'complex',
        'dict', 'dir', 'divmod', 'enumerate', 'filter', 'float', 'format',
        'frozenset', 'hasattr', 'hash', 'hex', 'id', 'int', 'isinstance',
        'issubclass', 'iter', 'len', 'list', 'map', 'max', 'min', 'next',
        'object', 'oct', 'ord', 'pow', 'print', 'property', 'range', 'repr',
        'reversed', 'round', 'set', 'slice', 'sorted', 'staticmethod', 'str',
        'sum', 'super', 'tuple', 'type', 'zip', 'Exception', 'ValueError',
        'TypeError', 'KeyError', 'IndexError', 'ZeroDivisionError',
        'ArithmeticError', 'RuntimeError', 'StopIteration', 'AttributeError',
        'ImportError', 'FileNotFoundError', 'PermissionError', 'enumerate',
    }
    return base - DANGEROUS_BUILTINS


def _monitor_memory(proc, memory_mb):
    """Windows 兜底内存限制：轮询子进程内存，超限即 kill。"""
    if os.name != 'nt' or not memory_mb:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t),
            ]

        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        h = k32.OpenProcess(0x0410, False, int(proc.pid))
        if not h:
            return
        try:
            limit = memory_mb * 1024 * 1024
            while proc.poll() is None:
                pmc = _PMC()
                pmc.cb = ctypes.sizeof(_PMC)
                if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    if pmc.WorkingSetSize > limit:
                        proc.kill()
                        return
                time.sleep(0.1)
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass


def execute(code: str, workdir: str = None, timeout: int = DEFAULT_TIMEOUT,
            max_memory_mb: int = None) -> dict:
    """在真子进程沙箱中执行代码。

    Args:
        code: 用户代码
        workdir: 会话工作目录（所有文件读写限制在此目录内）；None 时用临时目录
        timeout: 超时秒数
        max_memory_mb: 内存上限（MB），None 取环境变量 SANDBOX_MAX_MEMORY_MB 或 512
    """
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    max_memory_mb = max_memory_mb or int(os.environ.get('SANDBOX_MAX_MEMORY_MB', '512'))

    result = {
        'success': False, 'stdout': '', 'stderr': '',
        'files': [], 'execution_time_ms': 0,
    }

    tmp_dir = None
    if workdir:
        out_dir = os.path.abspath(workdir)
        os.makedirs(out_dir, exist_ok=True)
    else:
        tmp_dir = tempfile.mkdtemp(prefix='mcp_sandbox_')
        out_dir = tmp_dir

    is_valid, errors = validate_code(code, workdir=out_dir)
    if not is_valid:
        result['stderr'] = '; '.join(errors)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return result

    script = _build_sandbox_script(code, out_dir, max_memory_mb)

    env = {
        'PATH': os.environ.get('PATH', ''),
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONIOENCODING': 'utf-8',
        'HOME': tempfile.gettempdir(),
        'TMPDIR': tempfile.gettempdir(),
        # 单线程 BLAS/OpenMP：多线程时 OpenBLAS 会为每线程预留大量虚拟内存，
        # 在 RLIMIT_AS 限制下直接导入失败（Memory allocation still failed after 10 retries）
        'OMP_NUM_THREADS': '1',
        'OPENBLAS_NUM_THREADS': '1',
        'MKL_NUM_THREADS': '1',
        'NUMEXPR_NUM_THREADS': '1',
        'VECLIB_MAXIMUM_THREADS': '1',
    }
    # matplotlib 缓存目录（避免首次渲染报权限/只读问题）
    env['MPLCONFIGDIR'] = os.path.join(tempfile.gettempdir(), 'mplconfig')
    try:
        os.makedirs(env['MPLCONFIGDIR'], exist_ok=True)
    except Exception:
        pass

    start = time.time()
    try:
        # 基线快照：持久会话目录中可能留有历史产物（此前会话/执行的文件），
        # 只收集本次执行「新增或修改」的文件，避免历史文件被当作本次产物
        # 返回给调用方（如旧折线图混入新对话）。临时目录场景基线自然为空。
        baseline = _snapshot_dir(out_dir)
        proc = subprocess.Popen(
            [sys.executable, '-I', '-c', script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace', env=env,
            cwd=out_dir,
        )
        threading.Thread(target=_monitor_memory, args=(proc, max_memory_mb), daemon=True).start()
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            result['stderr'] = f"执行超时（{timeout}秒），进程已被终止"
            result['execution_time_ms'] = int((time.time() - start) * 1000)
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return result

        result['execution_time_ms'] = int((time.time() - start) * 1000)
        result['stdout'] = (stdout or '').strip()
        result['stderr'] = (stderr or '').strip()

        if proc.returncode != 0:
            result['success'] = False
            if not result['stderr']:
                result['stderr'] = f"进程退出码: {proc.returncode}"
        else:
            result['success'] = True

        result['files'] = _collect_files(out_dir, baseline=baseline)
        return result

    except Exception as e:
        result['stderr'] = f"沙箱错误: {type(e).__name__}: {e}"
        result['execution_time_ms'] = int((time.time() - start) * 1000)
        return result
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _snapshot_dir(out_dir):
    """目录基线快照：{绝对路径: (mtime_ns, size)}。执行前调用，供 _collect_files 做增量 diff。"""
    snap = {}
    if not os.path.isdir(out_dir):
        return snap
    for root, _dirs, filenames in os.walk(out_dir):
        for fn in filenames:
            fp = os.path.join(root, fn)
            try:
                st = os.stat(fp)
                snap[fp] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
    return snap


def _collect_files(out_dir, baseline=None):
    """收集输出目录内的文件元数据（不返回内容，由调用方按需读取）。

    baseline（执行前快照）时仅返回「新增或修改」的文件——持久会话目录中的
    历史产物不再混入本次执行的 files 返回；baseline=None 时保持全量收集
    （兼容临时目录等无历史场景）。
    """
    files = []
    if not os.path.isdir(out_dir):
        return files
    for root, _dirs, filenames in os.walk(out_dir):
        for fn in filenames:
            if fn.startswith('.'):
                continue
            fp = os.path.join(root, fn)
            if baseline is not None:
                try:
                    st = os.stat(fp)
                    sig = (st.st_mtime_ns, st.st_size)
                except OSError:
                    continue
                if baseline.get(fp) == sig:
                    continue  # 历史文件且本次未改动
            rel = os.path.relpath(fp, out_dir).replace('\\', '/')
            try:
                files.append({
                    'name': rel,
                    'size': os.path.getsize(fp),
                    'path': fp.replace('\\', '/'),
                })
            except Exception:
                pass
    return files
