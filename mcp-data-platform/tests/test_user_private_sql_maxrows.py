# -*- coding: utf-8 -*-
"""user_private_sql_query 行数上限回归测试。

max_rows 默认 1000 / 上限 5000；截断时返回提示（含 pandas 全量计算引导），
SQL 聚合能力不受影响。
"""
import os
import sqlite3
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.user_kb_sqlite_tools import (
    _HARD_MAX_ROWS,
    _user_private_sql_query,
    get_user_sqlite_path,
    init_user_dirs,
)

UID = '5e3158a5-test-uid'


@pytest.fixture()
def big_table(tmp_path):
    base = str(tmp_path)
    init_user_dirs(base)
    db = get_user_sqlite_path(base, UID)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sales(id INTEGER PRIMARY KEY, region TEXT, amount REAL)")
    conn.executemany(
        "INSERT INTO sales(region, amount) VALUES(?, ?)",
        [(f"区域{i % 7}", float(i)) for i in range(3000)],
    )
    conn.commit()
    conn.close()
    return base


def test_default_limit_1000_and_truncated_hint(big_table):
    out = _user_private_sql_query(big_table, UID, "SELECT * FROM sales")
    assert "最多返回 1000 行，已截断" in out
    assert out.count("\n") >= 1000  # 表头+分隔外的数据行
    assert "GROUP BY" in out and "pandas" in out  # 引导语
    assert get_user_sqlite_path(big_table, UID) in out  # 提示直连路径


def test_max_rows_param_respected(big_table):
    out = _user_private_sql_query(big_table, UID, "SELECT * FROM sales", max_rows=200)
    assert "最多返回 200 行，已截断" in out


def test_max_rows_clamped_to_hard_limit(big_table):
    # 表仅 3000 行，上限收紧到 5000 生效但不会触发截断提示
    out = _user_private_sql_query(big_table, UID, "SELECT * FROM sales", max_rows=99999)
    assert f"最多返回 {_HARD_MAX_ROWS} 行）" in out
    assert "已截断" not in out


def test_small_result_not_truncated(big_table):
    out = _user_private_sql_query(big_table, UID, "SELECT * FROM sales LIMIT 10")
    assert "已截断" not in out
    assert out.count("\n") == 11  # 1 头 + 1 分隔 + 10 行


def test_aggregation_unaffected(big_table):
    out = _user_private_sql_query(big_table, UID,
                                  "SELECT region, COUNT(*) AS cnt, SUM(amount) AS total "
                                  "FROM sales GROUP BY region ORDER BY region")
    assert "已截断" not in out
    assert "区域0" in out


def test_sqlite_missing_table_returns_exception_text(big_table):
    out = _user_private_sql_query(big_table, UID, "SELECT * FROM not_exist")
    assert "SQL执行异常" in out
