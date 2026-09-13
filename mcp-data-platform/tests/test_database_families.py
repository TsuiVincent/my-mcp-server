# -*- coding: utf-8 -*-
"""数据库扩展回归测试：类型别名归一化、默认端口、注册/查询分发、只读拦截。

不依赖真实数据库：新驱动族走 127.0.0.1:1 快速失败路径，
仅验证「归一化正确、分发路由正确、异常以文案返回不抛出」。
"""
import os
import sqlite3
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.database_tools import (
    _DB_DEFAULT_PORTS,
    _DB_TYPE_ALIASES,
    _init_store,
    _list_connections,
    _load_connection,
    _normalize_db_type,
    _query_clickhouse,
    _query_dm,
    _query_oracle,
    _query_sqlite,
    _query_sqlserver,
    _sanitize_sql,
    _save_connection,
    _validate_db_connection_type,
)

# ── 类型别名归一化 ──

@pytest.mark.parametrize("alias, family", [
    ("mysql", "mysql"), ("mariadb", "mysql"), ("tidb", "mysql"),
    ("oceanbase", "mysql"), ("doris", "mysql"), ("starrocks", "mysql"),
    ("postgresql", "postgresql"), ("postgres", "postgresql"),
    ("kingbase", "postgresql"), ("kingbasees", "postgresql"),
    ("opengauss", "postgresql"), ("gaussdb", "postgresql"),
    ("vastbase", "postgresql"), ("highgo", "postgresql"), ("oscar", "postgresql"),
    ("oracle", "oracle"),
    ("sqlserver", "sqlserver"), ("mssql", "sqlserver"),
    ("dm", "dm"), ("dameng", "dm"),
    ("clickhouse", "clickhouse"), ("ch", "clickhouse"),
    ("sqlite", "sqlite"),
    # 大小写与空白容错
    (" KingBase ", "postgresql"), ("DAMENG", "dm"),
])
def test_normalize_db_type(alias, family):
    assert _normalize_db_type(alias) == family


@pytest.mark.parametrize("bad", ["", None, "mongodb", "redis", "oracle11", "foo"])
def test_normalize_db_type_rejects_unknown(bad):
    assert _normalize_db_type(bad) is None


def test_validate_error_message_lists_families():
    msg = _validate_db_connection_type("mongodb")
    assert "不支持的数据库类型" in msg and "kingbase" in msg and "dm(达梦)" in msg


def test_alias_table_covers_all_default_ports():
    # 除文件型 SQLite（无端口概念）外，每个别名都应有默认端口定义
    non_file_types = set(_DB_TYPE_ALIASES) - {"sqlite"}
    assert non_file_types == set(_DB_DEFAULT_PORTS)


# ── 注册持久化（临时元数据库） ──

@pytest.fixture()
def meta_store(tmp_path):
    _init_store(str(tmp_path))
    yield
    # _init_store 每次以新路径覆盖全局状态，无需额外清理


def test_register_normalizes_family_and_port(meta_store):
    _save_connection("u1", "kb", {
        "db_type": _normalize_db_type("kingbase"),
        "host": "192.168.1.100", "port": _DB_DEFAULT_PORTS["kingbase"],
        "user": "r", "password": "p", "database": "sales", "extra": {},
    })
    cfg = _load_connection("u1", "kb")
    assert cfg["db_type"] == "postgresql"
    assert cfg["port"] == 54321

    _save_connection("u1", "dmdb", {
        "db_type": _normalize_db_type("dameng"),
        "host": "192.168.1.101", "port": _DB_DEFAULT_PORTS["dameng"],
        "user": "SYSDBA", "password": "p", "database": "SCHEMA_A", "extra": {},
    })
    assert _load_connection("u1", "dmdb")["db_type"] == "dm"
    assert _load_connection("u1", "dmdb")["port"] == 5236

    # 用户隔离
    assert _load_connection("u2", "kb") is None
    assert {c["name"] for c in _list_connections("u1")} == {"kb", "dmdb"}


# ── 只读拦截（全族共用） ──

@pytest.mark.parametrize("sql", [
    "DROP TABLE t", "delete from t", "INSERT INTO t VALUES(1)",
    "UPDATE t SET a=1", "CREATE TABLE t(a int)", "TRUNCATE TABLE t",
    "ATTACH DATABASE 'x' AS y",
])
def test_sanitize_blocks_writes(sql):
    assert "安全拦截" in _sanitize_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1", "with x as (select 1) select * from x",
    "SHOW TABLES", "DESCRIBE t", "EXPLAIN SELECT 1",
])
def test_sanitize_allows_reads(sql):
    assert _sanitize_sql(sql) is None


# ── SQLite 真实查询（端到端小回路） ──

def test_sqlite_query_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t(a INTEGER, b TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'x'), (2, 'y')")
    conn.commit()
    conn.close()

    out = _query_sqlite(str(db), "SELECT * FROM t ORDER BY a")
    assert "共 2 条记录" in out and "1 | x" in out
    assert "安全拦截" in _query_sqlite(str(db), "DELETE FROM t")


# ── 新驱动族：不可达地址快速失败，异常以文案返回（不要求真实库） ──

_UNREACHABLE = {"host": "127.0.0.1", "port": 1, "user": "u",
                "password": "p", "database": "db"}


def test_oracle_unreachable_returns_error_text():
    out = _query_oracle(_UNREACHABLE, "SELECT 1 FROM dual")
    assert out.startswith("【Oracle查询异常】") or "oracledb" in out


def test_sqlserver_unreachable_returns_error_text():
    out = _query_sqlserver(_UNREACHABLE, "SELECT 1")
    assert out.startswith("【SQL Server查询异常】") or "pymssql" in out


def test_dm_unreachable_returns_error_text():
    out = _query_dm(_UNREACHABLE, "SELECT 1")
    assert out.startswith("【达梦查询异常】") or "dmPython" in out


def test_clickhouse_unreachable_returns_error_text():
    out = _query_clickhouse(_UNREACHABLE, "SELECT 1")
    assert out.startswith("【ClickHouse查询异常】") or "clickhouse-connect" in out
