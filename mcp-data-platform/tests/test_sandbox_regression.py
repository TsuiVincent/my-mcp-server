# -*- coding: utf-8 -*-
"""沙箱既有能力回归测试（A1/A2/A3/A10）。

目的：确认「库级文件 I/O 路径校验」（D1 方向一）落地后，沙箱原有的
真子进程执行、AST 静态拦截、运行时文件收敛、超时 kill、产物收集与
会话目录持久化等能力未被破坏。
"""
import base64
import os
import shutil
import sys
import tempfile

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sandbox_runner import execute, validate_code


@pytest.fixture()
def workdir():
    d = tempfile.mkdtemp(prefix='mcp_sbx_reg_')
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _outside_path(workdir, name):
    """构造一个确定位于工作目录之外的绝对路径。"""
    return os.path.join(os.path.dirname(os.path.abspath(workdir)), name)


# ── A1：科学计算栈可正常执行并产出文件 ──

def test_pandas_analysis_end_to_end(workdir):
    code = (
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2, 3], 'b': [10, 20, 30]})\n"
        "df['c'] = df['a'] * df['b']\n"
        "df.to_csv('out.csv', index=False)\n"
        "print(df['c'].sum())\n"
    )
    res = execute(code, workdir=workdir, timeout=90)
    assert res['success'] is True, res['stderr']
    assert res['stdout'] == '140', res['stdout']
    assert any(f['name'] == 'out.csv' for f in res['files']), res['files']
    with open(os.path.join(workdir, 'out.csv'), encoding='utf-8') as fp:
        assert fp.readline().strip() == 'a,b,c'


def test_numpy_compute_and_save(workdir):
    code = (
        "import numpy as np\n"
        "arr = np.arange(10)\n"
        "np.save('arr.npy', arr)\n"
        "print(int(arr.sum()))\n"
    )
    res = execute(code, workdir=workdir, timeout=90)
    assert res['success'] is True, res['stderr']
    assert res['stdout'] == '45', res['stdout']
    assert any(f['name'] == 'arr.npy' for f in res['files']), res['files']


def test_matplotlib_savefig_relative(workdir):
    pytest.importorskip('matplotlib')
    code = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3], [1, 4, 9])\n"
        "plt.savefig('chart.png')\n"
        "print('ok')\n"
    )
    res = execute(code, workdir=workdir, timeout=120)
    assert res['success'] is True, res['stderr']
    assert any(f['name'] == 'chart.png' for f in res['files']), res['files']


def test_open_write_within_workdir(workdir):
    res = execute("open('note.txt', 'w').write('hello')", workdir=workdir, timeout=30)
    assert res['success'] is True, res['stderr']
    with open(os.path.join(workdir, 'note.txt'), encoding='utf-8') as fp:
        assert fp.read() == 'hello'


# ── A2：AST 静态拦截（既有防护未被削弱） ──

def test_blocked_import_outside_whitelist():
    for mod in ('os', 'subprocess', 'socket', 'sys', 'pathlib', 'shutil'):
        valid, errors = validate_code(f"import {mod}\nx = 1")
        assert not valid, f"{mod} 应被拦截"
        assert any('禁止导入模块' in e for e in errors), errors


def test_blocked_import_from_outside_whitelist():
    valid, errors = validate_code("from os import path\nx = 1")
    assert not valid and any('禁止导入模块' in e for e in errors), errors


def test_blocked_dangerous_builtins():
    for code, name in [
        ("eval('1+1')", 'eval'),
        ("exec('a=1')", 'exec'),
        ("getattr(object, 'x')", 'getattr'),
        ("__import__('os')", '__import__'),
        ("globals()", 'globals'),
    ]:
        valid, errors = validate_code(code)
        assert not valid, f"{name} 应被拦截"
        assert any(f'禁止调用: {name}()' in e for e in errors), errors


def test_blocked_dunder_escape():
    for code in ("x = ().__class__", "x = ''.__class__.__bases__", "x = y['__globals__']"):
        valid, errors = validate_code(code)
        assert not valid, f"{code} 应被拦截"
        assert any('禁止' in e for e in errors), errors


def test_blocked_shell_call_attribute():
    valid, errors = validate_code("obj.system('ls')")
    assert not valid and any('禁止调用: .system()' in e for e in errors), errors
    valid, errors = validate_code("obj.popen('ls')")
    assert not valid and any('禁止调用: .popen()' in e for e in errors), errors


def test_blocked_forbidden_syntax_nodes():
    for code, node in [
        ("raise ValueError('x')", 'Raise'),
        ("def f():\n    global x", 'Global'),
        ("x = 1\ndel x", 'Delete'),
        ("def g():\n    yield 1", 'Yield'),
    ]:
        valid, errors = validate_code(code)
        assert not valid, f"{node} 应被拦截"
        assert any(f'禁止语法: {node}' in e for e in errors), errors


def test_empty_and_syntax_error_rejected_by_static_scan():
    valid, errors = validate_code('   ')
    assert not valid and '代码为空' in errors[0], errors

    valid, errors = validate_code('def broken(:')
    assert not valid and any('语法错误' in e for e in errors), errors


def test_static_reject_short_circuits_execution(workdir):
    """静态拦截在预扫描阶段完成，不启动子进程。"""
    res = execute("import os\nprint('never')", workdir=workdir, timeout=30)
    assert res['success'] is False
    assert res['execution_time_ms'] == 0
    assert '禁止导入模块' in res['stderr']
    assert res['stdout'] == ''


# ── A3：超时终止 ──

def test_timeout_kills_process(workdir):
    res = execute("while True:\n    pass", workdir=workdir, timeout=2)
    assert res['success'] is False
    assert '执行超时' in res['stderr'], res['stderr']
    assert res['execution_time_ms'] < 20000, res['execution_time_ms']


def test_exception_propagates_to_stderr(workdir):
    res = execute("print('before')\n1 / 0", workdir=workdir, timeout=30)
    assert res['success'] is False
    assert 'ZeroDivisionError' in res['stderr'], res['stderr']
    assert res['stdout'] == 'before', res['stdout']


# ── A10：运行时文件收敛 / 产物收集 / 会话目录持久化 ──

def test_runtime_open_escape_blocked(workdir):
    """open() 仍由运行时 _safe_open 收敛（AST 层放行的分层不变式）。"""
    target = _outside_path(workdir, 'escape.txt')
    valid, _errors = validate_code(f"open({target!r}, 'w').write('x')", workdir=workdir)
    assert valid, "open() 应在 AST 层放行"

    res = execute(f"open({target!r}, 'w').write('x')", workdir=workdir, timeout=30)
    assert res['success'] is False
    assert '只允许在工作目录内操作文件' in res['stderr'], res['stderr']
    assert not os.path.exists(target)


def test_collected_files_relative_and_dotfiles_skipped(workdir):
    code = (
        "open('visible.txt', 'w').write('v')\n"
        "open('.hidden', 'w').write('h')\n"
    )
    res = execute(code, workdir=workdir, timeout=30)
    assert res['success'] is True, res['stderr']
    names = {f['name'] for f in res['files']}
    assert names == {'visible.txt'}, names
    entry = res['files'][0]
    assert entry['size'] == 1
    assert entry['path'].endswith('visible.txt')


def test_workdir_persists_across_calls(workdir):
    """两次调用共享会话目录，第二步能读取第一步的产物。"""
    first = execute("open('step1.txt', 'w').write('42')", workdir=workdir, timeout=30)
    assert first['success'] is True, first['stderr']

    second = execute("print(open('step1.txt').read())", workdir=workdir, timeout=30)
    assert second['success'] is True, second['stderr']
    assert second['stdout'] == '42', second['stdout']


def test_workdir_none_uses_temp_dir():
    res = execute("open('tmp.txt', 'w').write('t')\nprint('done')", workdir=None, timeout=30)
    assert res['success'] is True, res['stderr']
    assert res['stdout'] == 'done'


def test_stdout_captured_multiline(workdir):
    code = "print('line1')\nprint('line2')\nprint(1 + 2)\n"
    res = execute(code, workdir=workdir, timeout=30)
    assert res['success'] is True, res['stderr']
    assert res['stdout'].splitlines() == ['line1', 'line2', '3'], res['stdout']


# ── A11：模块级作用域（exec 单命名空间不变量）──

def test_module_level_comprehension_sees_outer_names(workdir):
    """模块级推导式/生成器表达式能读取外层变量（如 for 循环变量）。

    历史缺陷：沙箱曾用 exec(code, globals, locals) 双命名空间执行用户代码，
    语义等价于「类体作用域」——推导式只解析 globals、解析不到 locals 里的模块级
    名字，`for f in xs: any(f in n for n in names)` 抛 NameError: name 'f' is not
    defined（知识图谱技能的中文字体检测即因此失败）。修复后 globals 与 locals
    共用同一 dict，恢复标准模块作用域。
    """
    code = (
        "names = ['Noto Sans CJK SC', 'Microsoft YaHei']\n"
        "picked = ''\n"
        "for f in ['WenQuanYi Micro Hei', 'Microsoft YaHei']:\n"
        "    if any(f.lower() in n.lower() for n in names):\n"
        "        picked = f\n"
        "        break\n"
        "print(picked)\n"
        "print([n for n in names if n.endswith('YaHei')])\n"
    )
    res = execute(code, workdir=workdir, timeout=30)
    assert res['success'] is True, res['stderr']
    assert res['stdout'].splitlines() == ['Microsoft YaHei', "['Microsoft YaHei']"], res['stdout']


def test_module_level_generator_consumed_by_call(workdir):
    """模块级生成器表达式作为函数实参时同样可见外层变量。"""
    code = (
        "base = [1, 2, 3]\n"
        "k = 2\n"
        "print(sum(v * k for v in base))\n"
    )
    res = execute(code, workdir=workdir, timeout=30)
    assert res['success'] is True, res['stderr']
    assert res['stdout'] == '12', res['stdout']


# ── A8：图片产物内联 base64（平台据此托管 download_url 并在前端内联渲染）──

class _StubMCP:
    """最小 FastMCP 替身：捕获 @mcp.tool 注册的工具函数。"""

    def __init__(self):
        self.tools = {}

    def tool(self, name=None, description=None):
        def deco(fn):
            self.tools[name] = fn
            return fn
        return deco


@pytest.fixture()
def exec_tools(tmp_path):
    """在临时 base_dir 上注册 python 执行工具，返回 {工具名: 函数}。"""
    from tools.python_executor_tools import register_python_executor_tools

    stub = _StubMCP()
    register_python_executor_tools(stub, base_dir=str(tmp_path))
    return stub.tools


def test_exec_json_inlines_png_base64(exec_tools):
    """沙箱写出的 png 会被内联为 filename + base64_data。"""
    res = exec_tools['python_exec_json'](
        "open('trend.png', 'wb').write(b'\\x89PNG\\r\\n\\x1a\\n' + b'0' * 64)",
        user_id='artifact_u1',
    )
    assert res['success'] is True, res['stderr']
    pngs = [f for f in res['files'] if f['name'] == 'trend.png']
    assert len(pngs) == 1, res['files']
    assert pngs[0]['filename'] == 'trend.png'
    assert base64.b64decode(pngs[0]['base64_data']) == b'\x89PNG\r\n\x1a\n' + b'0' * 64


def test_exec_json_keeps_non_image_untouched(exec_tools):
    """非图片产物（csv）保持原结构，不内联 base64。"""
    res = exec_tools['python_exec_json'](
        "open('out.csv', 'w').write('a,b\\n1,2\\n')",
        user_id='artifact_u2',
    )
    assert res['success'] is True, res['stderr']
    csvs = [f for f in res['files'] if f['name'] == 'out.csv']
    assert len(csvs) == 1, res['files']
    assert 'base64_data' not in csvs[0]
    assert 'filename' not in csvs[0]


def test_attach_image_payloads_skips_oversize_and_missing(workdir):
    """超限或读取失败的图片跳过内联，不影响 files 其余字段。"""
    from tools.python_executor_tools import _MAX_INLINE_B64, _attach_image_payloads

    files = [
        {'name': 'big.png', 'size': _MAX_INLINE_B64 + 1, 'path': os.path.join(workdir, 'big.png')},
        {'name': 'gone.png', 'size': 10, 'path': os.path.join(workdir, 'not_exists.png')},
    ]
    _attach_image_payloads(files)
    for f in files:
        assert 'base64_data' not in f, f
    assert [f['name'] for f in files] == ['big.png', 'gone.png']

