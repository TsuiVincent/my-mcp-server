"""
数据库管理与分析工具

实现 SQLite / MySQL / PostgreSQL 的统一连接管理，支持只读 SQL 查询、
表结构查看与数据统计。本次升级要点：
- 连接持久化：注册信息落 SQLite 元数据库 {base_dir}/meta/connections.db，重启不丢；
- 密码加密：cryptography.Fernet（密钥取自 MCP_SECRET_KEY，缺省时落盘随机密钥文件）；
- 用户隔离：所有工具按 user_id 存取，互不可见；
- 只读强制：SQLite 使用 mode=ro URI，MySQL/PG 设置会话只读；
- 注入加固：表名/列名统一「校验 + 引号包裹」，标识符不再直接拼接；
- 连接复用：可用时走 DBUtils.PooledDB，不可用时自动降级为直连。

工具列表：
- db_register_connection: 注册数据库连接
- db_execute_query: 执行只读 SQL 查询
- db_get_table_schema: 获取表结构
- db_get_table_stats: 获取表数据统计
- db_list_connections: 列出已注册连接
"""

import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ===================== 元数据存储（连接持久化） =====================

_META_DB_PATH: Optional[str] = None
_STORE_LOCK = threading.Lock()
_fernet = None

# 连接池注册表 {('sqlite'|'mysql'|'postgresql', 标识) : PooledDB}
_POOLS: Dict[Any, Any] = {}
_POOLS_LOCK = threading.Lock()

# 禁止的关键字（防止写入/逃逸操作）
_DENY_SQL_KEYWORDS = {
    "drop", "alter", "insert", "delete", "update", "create",
    "truncate", "grant", "revoke", "exec", "execute", "replace",
    # 本次加固：阻断 SQLite 附加库 / 加载扩展 / PRAGMA 逃逸
    "attach", "detach", "pragma", "load_extension",
}

# 标识符中禁止出现的字符（引号/分隔符/控制字符）——防注入
_ILLEGAL_IDENT_CHARS = set("\"'\u0060;\\\x00\r\n\t")


def _default_base_dir() -> str:
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), "mcp-user-data")
    return "/data/mcp-user-data"


def _build_fernet(meta_dir: str):
    """构造密码加解密器；cryptography 不可用时返回 None（降级为编码存储）。"""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography 未安装，数据库密码将以编码形式存储（建议安装 cryptography）")
        return None

    secret = (os.environ.get("MCP_SECRET_KEY") or "").strip()
    key_file = os.path.join(meta_dir, "secret.key")
    if secret:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    elif os.path.exists(key_file):
        with open(key_file, "rb") as f:
            key = f.read().strip()
    else:
        key = Fernet.generate_key()
        with open(key_file, "wb") as f:
            f.write(key)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
    try:
        return Fernet(key)
    except Exception as e:
        logger.warning("Fernet 初始化失败，降级为编码存储: %s", e)
        return None


def _init_store(base_dir: str) -> None:
    """初始化元数据库（幂等）。"""
    global _META_DB_PATH, _fernet
    meta_dir = os.path.join(base_dir, "meta")
    os.makedirs(meta_dir, exist_ok=True)
    _META_DB_PATH = os.path.join(meta_dir, "connections.db")
    with _STORE_LOCK:
        conn = sqlite3.connect(_META_DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS connections (
                    user_id      TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    db_type      TEXT NOT NULL,
                    host         TEXT,
                    port         INTEGER,
                    username     TEXT,
                    password_enc TEXT,
                    database     TEXT,
                    extra        TEXT,
                    updated_at   TEXT,
                    PRIMARY KEY (user_id, name)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
    _fernet = _build_fernet(meta_dir)


def _encrypt_password(password: str) -> str:
    if not password:
        return ""
    if _fernet is not None:
        try:
            return "enc:" + _fernet.encrypt(password.encode("utf-8")).decode("ascii")
        except Exception as e:
            logger.warning("密码加密失败，降级为编码存储: %s", e)
    return "raw:" + base64.b64encode(password.encode("utf-8")).decode("ascii")


def _decrypt_password(blob: str) -> str:
    if not blob:
        return ""
    try:
        if blob.startswith("enc:") and _fernet is not None:
            return _fernet.decrypt(blob[4:].encode("ascii")).decode("utf-8")
        if blob.startswith("raw:"):
            return base64.b64decode(blob[4:]).decode("utf-8")
    except Exception as e:
        logger.warning("密码解密失败: %s", e)
    return ""


def _save_connection(user_id: str, name: str, cfg: Dict[str, Any]) -> None:
    if not _META_DB_PATH:
        raise RuntimeError("连接元数据库未初始化")
    with _STORE_LOCK:
        conn = sqlite3.connect(_META_DB_PATH)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO connections
                (user_id, name, db_type, host, port, username, password_enc,
                 database, extra, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, name, cfg.get("db_type", ""), cfg.get("host", ""),
                    int(cfg.get("port") or 0), cfg.get("user", ""),
                    _encrypt_password(cfg.get("password", "")),
                    cfg.get("database", ""),
                    json.dumps(cfg.get("extra", {}), ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
        finally:
            conn.close()


def _load_connection(user_id: str, name: str) -> Optional[Dict[str, Any]]:
    if not _META_DB_PATH:
        return None
    with _STORE_LOCK:
        conn = sqlite3.connect(_META_DB_PATH)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM connections WHERE user_id=? AND name=?",
                (user_id, name),
            ).fetchone()
        finally:
            conn.close()
    return _row_to_config(row) if row else None


def _list_connections(user_id: str) -> List[Dict[str, Any]]:
    if not _META_DB_PATH:
        return []
    with _STORE_LOCK:
        conn = sqlite3.connect(_META_DB_PATH)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM connections WHERE user_id=? ORDER BY name",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
    return [_row_to_config(r) for r in rows]


def _row_to_config(row) -> Dict[str, Any]:
    try:
        extra = json.loads(row["extra"]) if row["extra"] else {}
    except Exception:
        extra = {}
    return {
        "name": row["name"],
        "db_type": row["db_type"],
        "host": row["host"] or "",
        "port": row["port"] or 0,
        "user": row["username"] or "",
        "password": _decrypt_password(row["password_enc"] or ""),
        "database": row["database"] or "",
        "extra": extra,
    }


# ===================== SQL 安全检查 =====================

def _sanitize_sql(sql: str) -> Optional[str]:
    """SQL安全检查：仅允许只读查询"""
    if not sql or not sql.strip():
        return "【安全拦截】SQL 不能为空。"
    sql_lower = sql.lower().strip()

    for keyword in _DENY_SQL_KEYWORDS:
        # 使用单词边界匹配
        if re.search(r"\b" + keyword + r"\b", sql_lower):
            return f"【安全拦截】禁止执行 {keyword.upper()} 操作，仅允许只读查询。"

    if not sql_lower.startswith(("select", "show", "describe", "explain", "with")):
        return "【安全拦截】仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH 查询。"

    return None


def _validate_identifier(value: str, kind: str = "标识符") -> Optional[str]:
    """校验标识符（表名/列名）。

    允许中文、空格等常见列名，但显式拒绝引号/分隔符等可用于注入的字符，
    阻断「引号闭合 + 语句拼接」型注入。
    """
    if not value or not value.strip():
        return f"【错误】{kind}不能为空"
    if len(value) > 128:
        return f"【错误】{kind}过长（超过128字符）"
    if any(c in _ILLEGAL_IDENT_CHARS for c in value):
        return f"【错误】{kind}包含非法字符: {value!r}"
    return None


def _quote_ident(value: str, dialect: str = "sqlite") -> str:
    """按方言对标识符加引号并转义内部引号（校验通过后调用）。"""
    if dialect == "mysql":
        return "`" + value.replace("`", "``") + "`"
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    """按 SQL 字面量转义（用于 information_schema 过滤条件）。"""
    return "'" + value.replace("'", "''") + "'"


def _validate_db_connection_type(db_type: str) -> Optional[str]:
    """验证数据库类型"""
    allowed = ("sqlite", "mysql", "postgresql", "postgres")
    if db_type not in allowed:
        return f"【错误】不支持的数据库类型: {db_type}，支持: {', '.join(allowed)}"
    return None


# ===================== 连接获取（池化 + 降级） =====================

def _acquire(key: Any, creator) -> Any:
    """获取连接：优先连接池复用，任何异常均降级为直连。"""
    try:
        from dbutils.pooled_db import PooledDB
        with _POOLS_LOCK:
            pool = _POOLS.get(key)
            if pool is None:
                pool = PooledDB(creator=creator, maxconnections=5, blocking=True, ping=0)
                _POOLS[key] = pool
        return pool.connection()
    except Exception as e:
        logger.debug("连接池不可用(%s)，降级为直连: %s", key, e)
        return creator()


# ===================== SQLite 实现 =====================

def _sqlite_connect(db_path: str) -> sqlite3.Connection:
    """建立 SQLite 只读连接（mode=ro），支持连接池复用。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"SQLite数据库文件不存在: {db_path}")
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")  # 双保险只读
    return conn


@contextlib.contextmanager
def _sqlite_conn(db_path: str):
    conn = _acquire(("sqlite", db_path), lambda: _sqlite_connect(db_path))
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _query_sqlite(db_path: str, sql: str) -> str:
    """执行SQLite查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    try:
        with _sqlite_conn(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                if not rows:
                    return "查询结果：无匹配数据"
                result = _format_query_result(cols, rows)
                result.append(f"\n共 {len(rows)} 条记录")
                return "\n".join(result)
            return "查询已执行（无返回结果）"

    except Exception as e:
        return f"【SQLite查询异常】{str(e)}"


# ===================== MySQL 实现 =====================

def _mysql_connect(host: str, port: int, user: str, password: str, database: str) -> Any:
    """建立 MySQL 只读连接。"""
    try:
        import pymysql
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,  # 不自动提交，防止误操作
        )
    except ImportError:
        raise ImportError("pymysql 库未安装。请执行: pip install pymysql")
    try:
        with conn.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
    except Exception as e:
        logger.warning("设置 MySQL 会话只读失败（可能版本不支持）: %s", e)
    return conn


def _query_mysql(config: dict, sql: str) -> str:
    """执行MySQL查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    host = config.get("host", "localhost")
    port = int(config.get("port", 3306) or 3306)
    user = config.get("user", "root")
    database = config.get("database", "")
    key = ("mysql", host, port, user, database)

    try:
        conn = _acquire(
            key,
            lambda: _mysql_connect(host, port, user, config.get("password", ""), database),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                formatted_rows = [[row.get(col, "") for col in cols] for row in rows]
                cursor.close()
                if not formatted_rows:
                    return "查询结果：无匹配数据"
                result = _format_query_result(cols, formatted_rows)
                result.append(f"\n共 {len(formatted_rows)} 条记录")
                return "\n".join(result)
            cursor.close()
            return "查询已执行（无返回结果）"
        finally:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()

    except Exception as e:
        return f"【MySQL查询异常】{str(e)}"


# ===================== PostgreSQL 实现 =====================

def _pg_connect(host: str, port: int, user: str, password: str, database: str) -> Any:
    """建立 PostgreSQL 只读连接。"""
    try:
        import psycopg2
        import psycopg2.extras  # noqa: F401
    except ImportError:
        raise ImportError("psycopg2 库未安装。请执行: pip install psycopg2-binary")
    conn = psycopg2.connect(
        host=host, port=port, user=user, password=password, dbname=database
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _query_postgresql(config: dict, sql: str) -> str:
    """执行PostgreSQL查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    host = config.get("host", "localhost")
    port = int(config.get("port", 5432) or 5432)
    user = config.get("user", "postgres")
    database = config.get("database", "postgres")
    key = ("postgresql", host, port, user, database)

    try:
        conn = _acquire(
            key,
            lambda: _pg_connect(host, port, user, config.get("password", ""), database),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                cursor.close()
                if not rows:
                    return "查询结果：无匹配数据"
                result = _format_query_result(cols, rows)
                result.append(f"\n共 {len(rows)} 条记录")
                return "\n".join(result)
            cursor.close()
            return "查询已执行（无返回结果）"
        finally:
            conn.close()

    except Exception as e:
        return f"【PostgreSQL查询异常】{str(e)}"


# ===================== 通用工具函数 =====================

def _format_query_result(cols: list, rows: list) -> list:
    """格式化查询结果为表格"""
    result_lines = ["查询结果："]
    result_lines.append(" | ".join(str(c) for c in cols))
    result_lines.append("-" * 50)
    for row in rows[:200]:
        result_lines.append(" | ".join(str(item) for item in row))
    if len(rows) > 200:
        result_lines.append(f"... 已截断，共 {len(rows)} 行，仅显示前200行")
    return result_lines


def _get_table_schema_sqlite(db_path: str, table_name: str) -> str:
    """获取SQLite表结构"""
    err = _validate_identifier(table_name, "表名")
    if err:
        return err
    try:
        q = _quote_ident(table_name)
        with _sqlite_conn(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            )
            row = cursor.fetchone()
            if not row:
                return f"【提示】表 '{table_name}' 不存在"
            ddl = row[0]

            cursor.execute(f"SELECT COUNT(*) as cnt FROM {q}")
            count = cursor.fetchone()[0]

        return f"【表结构: {table_name}】\n{ddl}\n\n总记录数: {count}"
    except Exception as e:
        return f"【获取表结构失败】{str(e)}"


def _get_table_stats_sqlite(db_path: str, table_name: str) -> str:
    """获取SQLite表数据统计"""
    err = _validate_identifier(table_name, "表名")
    if err:
        return err
    try:
        tq = _quote_ident(table_name)
        with _sqlite_conn(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({tq})")
            columns = cursor.fetchall()

            stats_lines = [f"【表统计: {table_name}】"]
            for col in columns:
                col_name = col[1]
                col_type = col[2]
                if any(c in _ILLEGAL_IDENT_CHARS for c in str(col_name)):
                    stats_lines.append(f"  {col_name} ({col_type}): 列名含特殊字符，已跳过统计")
                    continue
                cq = _quote_ident(col_name)

                if str(col_type).upper() in ("INTEGER", "REAL", "FLOAT", "NUMERIC", "DOUBLE"):
                    cursor.execute(f"""
                        SELECT
                            COUNT(*) as count,
                            MIN({cq}) as min_val,
                            MAX({cq}) as max_val,
                            AVG({cq}) as avg_val
                        FROM {tq}
                        WHERE {cq} IS NOT NULL
                    """)
                    stat = cursor.fetchone()
                    if stat and stat[3] is not None:
                        stats_lines.append(
                            f"  {col_name} ({col_type}): "
                            f"count={stat[0]}, min={stat[1]}, max={stat[2]}, avg={stat[3]:.2f}"
                        )
                    else:
                        stats_lines.append(f"  {col_name} ({col_type})")
                else:
                    cursor.execute(f"""
                        SELECT COUNT(DISTINCT {cq}) as distinct_cnt,
                               COUNT(*) as total
                        FROM {tq}
                    """)
                    stat = cursor.fetchone()
                    distinct_cnt = stat[0] if stat else 0
                    total = stat[1] if stat else 0
                    null_count = (total - distinct_cnt) if total else 0
                    stats_lines.append(
                        f"  {col_name} ({col_type}): distinct={distinct_cnt}, "
                        f"total={total}, nulls={null_count}"
                    )

            cursor.execute(f"SELECT COUNT(*) FROM {tq}")
            total = cursor.fetchone()[0]
            stats_lines.append(f"\n总记录数: {total}")
        return "\n".join(stats_lines)
    except Exception as e:
        return f"【统计失败】{str(e)}"


# ===================== 注册函数 =====================

def register_database_tools(mcp, base_dir: str = None):
    """注册数据库管理工具到 MCP 服务器

    Args:
        base_dir: 用户数据根目录；连接元数据库位于 {base_dir}/meta/connections.db
    """
    try:
        _init_store(base_dir or _default_base_dir())
    except Exception as e:
        logger.error("连接元数据库初始化失败: %s", e)

    @mcp.tool(
        name="db_register_connection",
        description=(
            "注册新的数据库连接配置(仅支持内网数据库)，配置持久化保存、按用户隔离。"
            "Args: name(连接名称), db_type(数据库类型:sqlite/mysql/postgresql), "
            "host(主机地址), port(端口), user(用户名), password(密码), "
            "database(数据库名；SQLite 填文件绝对路径), extra_params(JSON格式额外参数,可选), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def db_register_connection(name: str, db_type: str, host: str = "localhost", port: int = 0,
                               user: str = "", password: str = "", database: str = "",
                               extra_params: str = "", user_id: str = "default") -> str:
        error = _validate_db_connection_type(db_type)
        if error:
            return error

        name_err = _validate_identifier(name, "连接名称")
        if name_err:
            return name_err

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

        cfg = {
            "db_type": db_type,
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "extra": extra,
        }
        try:
            _save_connection(user_id or "default", name, cfg)
        except Exception as e:
            return f"【错误】连接保存失败: {e}"

        host_display = database if db_type == "sqlite" else f"{host}:{port}/{database}"
        return f"【已注册】连接 '{name}' ({db_type}:{host_display})"

    @mcp.tool(
        name="db_execute_query",
        description=(
            "对已注册的数据库执行只读SQL查询(SELECT/SHOW/DESCRIBE/EXPLAIN/WITH)。"
            "Args: connection_name(已注册的连接名称), sql(SQL查询语句), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def db_execute_query(connection_name: str, sql: str, user_id: str = "default") -> str:
        uid = user_id or "default"
        config = _load_connection(uid, connection_name)
        if not config:
            names = [c["name"] for c in _list_connections(uid)]
            return f"【错误】连接 '{connection_name}' 未注册。可用连接: {names}"

        db_type = config["db_type"]
        try:
            if db_type == "sqlite":
                return _query_sqlite(config["database"], sql)
            elif db_type == "mysql":
                return _query_mysql(config, sql)
            elif db_type in ("postgresql", "postgres"):
                return _query_postgresql(config, sql)
            return f"【错误】不支持的数据库类型: {db_type}"
        except Exception as e:
            return f"【查询异常】{str(e)}"

    @mcp.tool(
        name="db_get_table_schema",
        description=(
            "获取指定表的DDL结构。Args: connection_name(连接名称), table_name(表名), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def db_get_table_schema(connection_name: str, table_name: str,
                            user_id: str = "default") -> str:
        uid = user_id or "default"
        config = _load_connection(uid, connection_name)
        if not config:
            return f"【错误】连接 '{connection_name}' 未注册"

        name_err = _validate_identifier(table_name, "表名")
        if name_err:
            return name_err

        if config["db_type"] == "sqlite":
            return _get_table_schema_sqlite(config["database"], table_name)

        # MySQL/PostgreSQL 通过查询 information_schema（表名走字面量转义）
        sql = (
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = "
            f"{_quote_literal(table_name)} ORDER BY ordinal_position"
        )
        try:
            if config["db_type"] == "mysql":
                return _query_mysql(config, sql)
            return _query_postgresql(config, sql)
        except Exception as e:
            return f"【获取表结构失败】{str(e)}"

    @mcp.tool(
        name="db_get_table_stats",
        description=(
            "获取表数据统计分析(各列的值分布、极值、空值率等)。"
            "Args: connection_name(连接名称), table_name(表名), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def db_get_table_stats(connection_name: str, table_name: str,
                           user_id: str = "default") -> str:
        uid = user_id or "default"
        config = _load_connection(uid, connection_name)
        if not config:
            return f"【错误】连接 '{connection_name}' 未注册"
        if config["db_type"] == "sqlite":
            return _get_table_stats_sqlite(config["database"], table_name)
        return "【提示】表统计功能当前仅支持SQLite。请使用 db_execute_query 手动执行分析SQL。"

    @mcp.tool(
        name="db_list_connections",
        description="列出当前用户已注册的数据库连接（密码已脱敏）。Args: user_id(当前登录用户ID,默认default)"
    )
    def db_list_connections(user_id: str = "default") -> str:
        uid = user_id or "default"
        connections = _list_connections(uid)
        if not connections:
            return "【提示】暂无已注册的数据库连接"
        lines = ["【已注册的数据库连接】"]
        for cfg in connections:
            db_type = cfg["db_type"]
            if db_type == "sqlite":
                host_display = cfg["database"]
            else:
                host_display = f"{cfg['host']}:{cfg['port']}/{cfg['database']}"
            lines.append(f"  {cfg.get('name', '?')}: {db_type}://{host_display}")
        return "\n".join(lines)

    logger.info("数据库管理工具已注册（持久化+加密+用户隔离）")
