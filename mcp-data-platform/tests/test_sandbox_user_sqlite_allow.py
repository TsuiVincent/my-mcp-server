# -*- coding: utf-8 -*-
"""沙箱库级 I/O 白名单测试：本人私有 SQLite 库放行，其他越界路径仍拦截。"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sandbox_runner import (
    _escapes_workdir,
    _user_private_db_path,
    validate_code,
)

UID = '5e3158a5-test-uid'
BASE = '/data/mcp-user-data'
WORKDIR = f'{BASE}/sandbox/{UID}'
OWN_DB = f'{BASE}/user_sqlite/{UID}_private.db'


def test_own_private_db_path_derived_from_workdir():
    assert _user_private_db_path(WORKDIR).replace('\\', '/') == OWN_DB


def test_own_private_db_allowed():
    assert _escapes_workdir(OWN_DB, WORKDIR) is False


def test_other_user_private_db_still_blocked():
    other = f'{BASE}/user_sqlite/other-user_private.db'
    assert _escapes_workdir(other, WORKDIR) is True


def test_other_absolute_paths_still_blocked():
    assert _escapes_workdir('/etc/passwd', WORKDIR) is True
    assert _escapes_workdir(f'{BASE}/raw_files/x.csv', WORKDIR) is True


def test_relative_paths_unchanged():
    assert _escapes_workdir('out.csv', WORKDIR) is False
    assert _escapes_workdir('../out.csv', WORKDIR) is True


def test_validate_code_allows_own_db_via_sqlite3_pandas():
    code = (
        "import sqlite3\n"
        "import pandas as pd\n"
        f"conn = sqlite3.connect('{OWN_DB}')\n"
        "df = pd.read_sql('SELECT * FROM sales', conn)\n"
        "df.to_csv('export.csv')\n"
    )
    ok, errors = validate_code(code, workdir=WORKDIR)
    assert ok, errors


def test_validate_code_blocks_other_db_via_connect():
    code = (
        "import sqlite3\n"
        f"conn = sqlite3.connect('{BASE}/user_sqlite/other_user_private.db')\n"
    )
    ok, errors = validate_code(code, workdir=WORKDIR)
    assert not ok
    assert any('越界' in e for e in errors)


def test_file_uri_own_db_allowed_other_blocked():
    assert _escapes_workdir(f'file:{OWN_DB}?mode=ro', WORKDIR) is False
    assert _escapes_workdir(f'file:{BASE}/user_sqlite/other_private.db?mode=ro', WORKDIR) is True
