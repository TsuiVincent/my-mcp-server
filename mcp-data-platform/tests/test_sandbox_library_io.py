# -*- coding: utf-8 -*-
"""库级文件 I/O 越界校验（D1）回归测试。

pandas/numpy/matplotlib 等 C 扩展的文件读写函数直接调用 libc，绕过运行时
_safe_open，必须在 AST 预扫描阶段按「路径字面量」做工作目录收敛。
"""
import os
import sys
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sandbox_runner import execute, validate_code

WORKDIR = os.path.abspath(os.path.join(os.sep, 'data', 'mcp-user-data', 'sandbox', 'u1'))
OUTSIDE = os.path.abspath(os.path.join(os.sep, 'etc', 'hostname'))
OUTSIDE_CSV = os.path.abspath(os.path.join(os.sep, 'tmp', 'escape_write.csv'))


def _blocked(code):
    valid, errors = validate_code(code, workdir=WORKDIR)
    assert not valid, f"应被拦截却通过: {code}"
    assert any('库级文件 I/O 越界' in e for e in errors), errors


def _allowed(code):
    valid, errors = validate_code(code, workdir=WORKDIR)
    assert valid, f"应放行却被拦截: {code} -> {errors}"


# ── 越界应拦截 ──

def test_pandas_read_csv_outside_blocked():
    _blocked(f"import pandas as pd\ndf = pd.read_csv({OUTSIDE!r}, header=None)")


def test_pandas_to_csv_outside_blocked():
    _blocked(f"import pandas as pd\npd.DataFrame({{'a': [1]}}).to_csv({OUTSIDE_CSV!r}, index=False)")


def test_numpy_load_outside_blocked():
    _blocked(f"import numpy as np\narr = np.load({OUTSIDE + '.npy'!r})")


def test_numpy_save_outside_blocked():
    _blocked(f"import numpy as np\nnp.save({OUTSIDE + '.npy'!r}, [1, 2, 3])")


def test_matplotlib_savefig_outside_blocked():
    _blocked(f"import matplotlib.pyplot as plt\nplt.savefig({OUTSIDE_CSV + '.png'!r})")


def test_relative_parent_escape_blocked():
    _blocked("import pandas as pd\npd.read_csv('../../../../etc/hostname')")


def test_path_keyword_arg_blocked():
    _blocked(f"import pandas as pd\npd.read_csv(filepath_or_buffer={OUTSIDE!r})")


def test_concatenated_literal_blocked():
    _blocked("import pandas as pd\npd.read_csv('/et' + 'c/hostname')")


# ── 工作目录内应放行 ──

def test_relative_path_allowed():
    _allowed("import pandas as pd\ndf = pd.read_csv('data.csv')")


def test_relative_output_allowed():
    _allowed("import pandas as pd\ndf = pd.DataFrame({'a': [1]})\ndf.to_csv('out/result.csv', index=False)")


def test_numpy_relative_allowed():
    _allowed("import numpy as np\nnp.save('arr.npy', [1, 2, 3])")


def test_matplotlib_relative_allowed():
    _allowed("import matplotlib.pyplot as plt\nplt.savefig('chart.png')")


def test_absolute_path_inside_workdir_allowed():
    inside = os.path.join(WORKDIR, 'data.csv')
    _allowed(f"import pandas as pd\npd.read_csv({inside!r})")


def test_builtin_open_still_ast_allowed():
    """open() 由运行时 _safe_open 收敛，AST 层保持放行（分层不变）。"""
    _allowed("open('ok.txt', 'w').write('hi')")


def test_non_literal_path_not_caught():
    """已知限制：变量拼接路径无法静态判定，需 OS 级隔离兜底。"""
    _allowed(f"import pandas as pd\np = {OUTSIDE!r}\npd.read_csv(p)")


# ── 运行时端到端 ──

def test_execute_blocks_library_io_escape():
    """越界调用在预扫描阶段即被拒（不依赖 pandas 是否安装）。"""
    res = execute(f"import pandas as pd\ndf = pd.read_csv({OUTSIDE!r})", timeout=30)
    assert res['success'] is False
    assert '库级文件 I/O 越界' in res['stderr']
    assert res['execution_time_ms'] == 0


def test_execute_allows_relative_write():
    workdir = tempfile.mkdtemp(prefix='mcp_sbx_test_')
    try:
        res = execute("open('ok.txt', 'w').write('hi')", workdir=workdir, timeout=30)
        assert res['success'] is True, res['stderr']
        assert any(f['name'] == 'ok.txt' for f in res['files']), res['files']
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
