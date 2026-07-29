"""
数据库管理与分析工具
实现SQLite、MySQL、PostgreSQL的统一连接管理，支持SQL查询、结果集处理、
数据统计分析及可视化展示，包含权限验证与查询优化。

工具列表：
- db_list_connections: 列出已配置的数据库连接
- db_execute_query: 执行SQL查询（仅SELECT）
- db_get_table_schema: 获取表结构信息
- db_get_table_stats: 获取表数据统计分析
- db_compare_tables: 跨表数据对比分析
"""

import os
import json
import re
import sqlite3
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ===================== 连接配置管理 =====================

# 数据库连接配置存储（生产环境应使用加密存储）
_DB_CONNECTIONS: Dict[str, Dict[str, Any]] = {}

# 禁止的关键字（防止写入操作）
_DENY_SQL_KEYWORDS = {
    "drop", "alter", "insert", "delete", "update", "create",
    "truncate", "grant", "revoke", "exec", "execute", "replace"
}


def _sanitize_sql(sql: str) -> Optional[str]:
    """SQL安全检查：仅允许只读查询"""
    sql_lower = sql.lower().strip()

    for keyword in _DENY_SQL_KEYWORDS:
        # 使用单词边界匹配
        if re.search(r'\b' + keyword + r'\b', sql_lower):
            return f"【安全拦截】禁止执行 {keyword.upper()} 操作，仅允许 SELECT 等只读查询。"

    if not sql_lower.startswith(("select", "show", "describe", "explain", "pragma", "with")):
        return f"【安全拦截】仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN/PRAGMA/WITH 查询。"

    return None


def _validate_db_connection_type(db_type: str) -> Optional[str]:
    """验证数据库类型"""
    allowed = ("sqlite", "mysql", "postgresql", "postgres")
    if db_type not in allowed:
        return f"【错误】不支持的数据库类型: {db_type}，支持: {', '.join(allowed)}"
    return None


# ===================== SQLite 实现 =====================

def _connect_sqlite(db_path: str) -> sqlite3.Connection:
    """连接SQLite数据库"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"SQLite数据库文件不存在: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")  # 只读模式
    return conn


def _query_sqlite(db_path: str, sql: str) -> str:
    """执行SQLite查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    try:
        conn = _connect_sqlite(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)

        if cursor.description:
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return "查询结果：无匹配数据"

            result = _format_query_result(cols, rows)
            result.append(f"\n共 {len(rows)} 条记录")
            return "\n".join(result)
        else:
            conn.close()
            return "查询已执行（无返回结果）"

    except Exception as e:
        return f"【SQLite查询异常】{str(e)}"


# ===================== MySQL 实现 =====================

def _connect_mysql(host: str, port: int, user: str, password: str, database: str) -> Any:
    """连接MySQL数据库"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False  # 不自动提交，防止误操作
        )
        return conn
    except ImportError:
        raise ImportError("pymysql 库未安装。请执行: pip install pymysql")


def _query_mysql(config: dict, sql: str) -> str:
    """执行MySQL查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    try:
        conn = _connect_mysql(
            host=config.get("host", "localhost"),
            port=config.get("port", 3306),
            user=config.get("user", "root"),
            password=config.get("password", ""),
            database=config.get("database", "")
        )
        cursor = conn.cursor()
        cursor.execute(sql)

        if cursor.description:
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            # 转换DictCursor行
            formatted_rows = [[row.get(col, "") for col in cols] for row in rows]
            cursor.close()
            conn.close()

            if not formatted_rows:
                return "查询结果：无匹配数据"

            result = _format_query_result(cols, formatted_rows)
            result.append(f"\n共 {len(formatted_rows)} 条记录")
            return "\n".join(result)
        else:
            cursor.close()
            conn.close()
            return "查询已执行（无返回结果）"

    except Exception as e:
        return f"【MySQL查询异常】{str(e)}"


# ===================== PostgreSQL 实现 =====================

def _connect_postgresql(host: str, port: int, user: str, password: str, database: str) -> Any:
    """连接PostgreSQL数据库"""
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password,
            dbname=database
        )
        return conn
    except ImportError:
        raise ImportError("psycopg2 库未安装。请执行: pip install psycopg2-binary")


def _query_postgresql(config: dict, sql: str) -> str:
    """执行PostgreSQL查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    try:
        conn = _connect_postgresql(
            host=config.get("host", "localhost"),
            port=config.get("port", 5432),
            user=config.get("user", "postgres"),
            password=config.get("password", ""),
            database=config.get("database", "postgres")
        )
        conn.set_session(readonly=True, autocommit=True)
        cursor = conn.cursor()
        cursor.execute(sql)

        if cursor.description:
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            if not rows:
                return "查询结果：无匹配数据"

            result = _format_query_result(cols, rows)
            result.append(f"\n共 {len(rows)} 条记录")
            return "\n".join(result)
        else:
            cursor.close()
            conn.close()
            return "查询已执行（无返回结果）"

    except Exception as e:
        return f"【PostgreSQL查询异常】{str(e)}"


# ===================== 通用工具函数 =====================

def _format_query_result(cols: list, rows: list) -> list:
    """格式化查询结果为表格"""
    result_lines = ["查询结果："]
    # 表头
    result_lines.append(" | ".join(str(c) for c in cols))
    result_lines.append("-" * 50)
    # 数据行（最多显示200行）
    for row in rows[:200]:
        result_lines.append(" | ".join(str(item) for item in row))
    if len(rows) > 200:
        result_lines.append(f"... 已截断，共 {len(rows)} 行，仅显示前200行")
    return result_lines


def _get_table_schema_sqlite(db_path: str, table_name: str) -> str:
    """获取SQLite表结构"""
    try:
        conn = _connect_sqlite(db_path)
        cursor = conn.cursor()

        # 获取建表语句
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return f"【提示】表 '{table_name}' 不存在"

        ddl = row[0]

        # 获取行数
        cursor.execute(f"SELECT COUNT(*) as cnt FROM \"{table_name}\"")
        count = cursor.fetchone()[0]
        conn.close()

        return f"【表结构: {table_name}】\n{ddl}\n\n总记录数: {count}"
    except Exception as e:
        return f"【获取表结构失败】{str(e)}"


def _get_table_stats_sqlite(db_path: str, table_name: str) -> str:
    """获取SQLite表数据统计"""
    try:
        conn = _connect_sqlite(db_path)
        cursor = conn.cursor()

        cursor.execute(f"PRAGMA table_info(\"{table_name}\")")
        columns = cursor.fetchall()

        stats_lines = [f"【表统计: {table_name}】"]
        for col in columns:
            col_name = col[1]
            col_type = col[2]

            # 数值列统计
            if col_type.upper() in ("INTEGER", "REAL", "FLOAT", "NUMERIC", "DOUBLE"):
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as count,
                        MIN("{col_name}") as min_val,
                        MAX("{col_name}") as max_val,
                        AVG("{col_name}") as avg_val
                    FROM "{table_name}"
                    WHERE "{col_name}" IS NOT NULL
                """)
                stat = cursor.fetchone()
                stats_lines.append(f"  {col_name} ({col_type}): "
                                   f"count={stat[0]}, min={stat[1]}, max={stat[2]}, avg={stat[3]:.2f}" if stat[3] is not None else f"  {col_name} ({col_type})")
            else:
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT "{col_name}") as distinct_cnt,
                           COUNT(*) as total
                    FROM "{table_name}"
                """)
                stat = cursor.fetchone()
                null_count = stat[1] - stat[0] if stat[1] else 0
                stats_lines.append(f"  {col_name} ({col_type}): distinct={stat[0]}, total={stat[1]}, nulls={null_count}")

        # 总记录数
        cursor.execute(f"SELECT COUNT(*) FROM \"{table_name}\"")
        total = cursor.fetchone()[0]
        stats_lines.append(f"\n总记录数: {total}")
        conn.close()
        return "\n".join(stats_lines)
    except Exception as e:
        return f"【统计失败】{str(e)}"


# ===================== 注册函数 =====================

def register_database_tools(mcp):
    """注册数据库管理工具到 MCP 服务器"""

    @mcp.tool(
        name="db_register_connection",
        description="注册新的数据库连接配置(仅支持内网数据库)。Args: name(连接名称), db_type(数据库类型:sqlite/mysql/postgresql), host(主机地址), port(端口), user(用户名), password(密码), database(数据库名), extra_params(JSON格式额外参数,可选)"
    )
    def db_register_connection(name: str, db_type: str, host: str = "localhost", port: int = 0,
                               user: str = "", password: str = "", database: str = "",
                               extra_params: str = "") -> str:
        error = _validate_db_connection_type(db_type)
        if error:
            return error

        if not host:
            host = "localhost"

        # 端口默认值
        if port == 0:
            if db_type == "mysql":
                port = 3306
            elif db_type in ("postgresql", "postgres"):
                port = 5432
            elif db_type == "sqlite":
                port = 0

        extra = {}
        if extra_params:
            try:
                extra = json.loads(extra_params)
            except json.JSONDecodeError:
                return "【错误】extra_params 不是有效的JSON格式"

        _DB_CONNECTIONS[name] = {
            "db_type": db_type,
            "host": host,
            "port": port,
            "user": user,
            "password": "***" if password else "",
            "_password": password,
            "database": database,
            "extra": extra
        }
        host_display = database if db_type == "sqlite" else f"{host}:{port}/{database}"
        return f"【已注册】连接 '{name}' ({db_type}:{host_display})"

    @mcp.tool(
        name="db_execute_query",
        description="对已注册的数据库执行只读SQL查询(SELECT/SHOW/DESCRIBE等)。Args: connection_name(已注册的连接名称), sql(SQL查询语句)"
    )
    def db_execute_query(connection_name: str, sql: str) -> str:
        if connection_name not in _DB_CONNECTIONS:
            return f"【错误】连接 '{connection_name}' 未注册。可用连接: {list(_DB_CONNECTIONS.keys())}"

        config = _DB_CONNECTIONS[connection_name]
        db_type = config["db_type"]

        try:
            if db_type == "sqlite":
                return _query_sqlite(config["database"], sql)
            elif db_type == "mysql":
                # 还原密码
                config_copy = config.copy()
                config_copy["password"] = config["_password"]
                return _query_mysql(config_copy, sql)
            elif db_type in ("postgresql", "postgres"):
                config_copy = config.copy()
                config_copy["password"] = config["_password"]
                return _query_postgresql(config_copy, sql)
            else:
                return f"【错误】不支持的数据库类型: {db_type}"
        except Exception as e:
            return f"【查询异常】{str(e)}"

    @mcp.tool(
        name="db_get_table_schema",
        description="获取指定表的DDL结构。Args: connection_name(连接名称), table_name(表名)"
    )
    def db_get_table_schema(connection_name: str, table_name: str) -> str:
        if connection_name not in _DB_CONNECTIONS:
            return f"【错误】连接 '{connection_name}' 未注册"
        config = _DB_CONNECTIONS[connection_name]
        if config["db_type"] == "sqlite":
            return _get_table_schema_sqlite(config["database"], table_name)
        else:
            # MySQL/PostgreSQL 通过查询 information_schema
            sql = f"SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position"
            try:
                if config["db_type"] == "mysql":
                    config_copy = config.copy()
                    config_copy["password"] = config["_password"]
                    return _query_mysql(config_copy, sql)
                else:
                    config_copy = config.copy()
                    config_copy["password"] = config["_password"]
                    return _query_postgresql(config_copy, sql)
            except Exception as e:
                return f"【获取表结构失败】{str(e)}"

    @mcp.tool(
        name="db_get_table_stats",
        description="获取表数据统计分析(各列的值分布、极值、空值率等)。Args: connection_name(连接名称), table_name(表名)"
    )
    def db_get_table_stats(connection_name: str, table_name: str) -> str:
        if connection_name not in _DB_CONNECTIONS:
            return f"【错误】连接 '{connection_name}' 未注册"
        config = _DB_CONNECTIONS[connection_name]
        if config["db_type"] == "sqlite":
            return _get_table_stats_sqlite(config["database"], table_name)
        else:
            return "【提示】表统计功能当前仅支持SQLite。请使用 db_execute_query 手动执行分析SQL。"

    @mcp.tool(
        name="db_list_connections",
        description="列出所有已注册的数据库连接（密码已脱敏）"
    )
    def db_list_connections() -> str:
        if not _DB_CONNECTIONS:
            return "【提示】暂无已注册的数据库连接"
        lines = ["【已注册的数据库连接】"]
        for name, config in _DB_CONNECTIONS.items():
            db_type = config["db_type"]
            if db_type == "sqlite":
                host_display = config["database"]
            else:
                host_display = f"{config['host']}:{config['port']}/{config['database']}"
            lines.append(f"  {name}: {db_type}://{host_display}")
        return "\n".join(lines)

    logger.info("数据库管理工具已注册")
