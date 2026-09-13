"""
数据库管理与分析工具

实现 SQLite / MySQL 族 / PostgreSQL 族 / Oracle / SQL Server / 达梦 / ClickHouse
的统一连接管理，支持只读 SQL 查询、表结构查看与数据统计。
兼容协议库通过「类型别名 → 驱动族」归一化接入，无需独立驱动：
- MySQL 协议族：MariaDB、TiDB、OceanBase(MySQL模式)、TDSQL、PolarDB、Doris、StarRocks
- PostgreSQL 协议族：人大金仓 KingbaseES、openGauss/GaussDB、Vastbase、瀚高 HighGo、神通 Oscar

本次升级要点：
- 连接持久化：注册信息落 SQLite 元数据库 {base_dir}/meta/connections.db，重启不丢；
- 密码加密：cryptography.Fernet（密钥取自 MCP_SECRET_KEY，缺省时落盘随机密钥文件）；
- 用户隔离：所有工具按 user_id 存取，互不可见；
- 只读强制：SQLite 使用 mode=ro URI，MySQL/PG 设置会话只读，Oracle/达梦设只读事务，
  全族统一 SQL 关键字黑名单兜底；
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
    """验证数据库类型（返回归一化后的驱动族，非法类型返回错误文案；兼容旧调用）"""
    if _normalize_db_type(db_type):
        return None
    return (
        f"【错误】不支持的数据库类型: {db_type}。支持: sqlite；"
        "MySQL 协议族 mysql/mariadb/tidb/oceanbase/tdsql/polardb/doris/starrocks；"
        "PostgreSQL 协议族 postgresql/kingbase/opengauss/gaussdb/vastbase/highgo/oscar；"
        "以及 oracle、sqlserver、dm(达梦)、clickhouse"
    )


# ===================== 数据库类型别名与驱动族 =====================
# 按「协议/驱动族」归一：兼容 MySQL / PostgreSQL 协议的国产与分布式库
# 直接复用现有 pymysql / psycopg2 实现，无需独立驱动。

_DB_TYPE_ALIASES: Dict[str, str] = {
    # SQLite
    "sqlite": "sqlite",
    # MySQL 协议族（pymysql）
    "mysql": "mysql", "mariadb": "mysql", "tidb": "mysql",
    "oceanbase": "mysql", "tdsql": "mysql", "polardb": "mysql",
    "doris": "mysql", "starrocks": "mysql",
    # PostgreSQL 协议族（psycopg2）
    "postgresql": "postgresql", "postgres": "postgresql",
    "kingbase": "postgresql", "kingbasees": "postgresql",   # 人大金仓
    "opengauss": "postgresql", "gaussdb": "postgresql",      # 华为 openGauss/GaussDB
    "vastbase": "postgresql",                                 # 海量数据库 Vastbase G100
    "highgo": "postgresql",                                   # 瀚高
    "oscar": "postgresql",                                    # 神舟通用
    # 独立驱动
    "oracle": "oracle",
    "sqlserver": "sqlserver", "mssql": "sqlserver",
    "dm": "dm", "dameng": "dm",                               # 达梦 DM8
    "clickhouse": "clickhouse", "ch": "clickhouse",
}

# 各类型的默认端口（按用户传入的原始别名匹配，未命中则保持 0）
_DB_DEFAULT_PORTS: Dict[str, int] = {
    "mysql": 3306, "mariadb": 3306, "tidb": 4000, "oceanbase": 2881,
    "tdsql": 3306, "polardb": 3306, "doris": 9030, "starrocks": 9030,
    "postgresql": 5432, "postgres": 5432, "kingbase": 54321, "kingbasees": 54321,
    "opengauss": 5432, "gaussdb": 8000, "vastbase": 5432, "highgo": 5866,
    "oscar": 2003,
    "oracle": 1521, "sqlserver": 1433, "mssql": 1433,
    "dm": 5236, "dameng": 5236, "clickhouse": 8123, "ch": 8123,
}


def _normalize_db_type(db_type: str) -> Optional[str]:
    """把用户传入的数据库类型归一化为驱动族。

    返回 sqlite/mysql/postgresql/oracle/sqlserver/dm/clickhouse 之一；
    无法识别时返回 None。
    """
    if not db_type:
        return None
    return _DB_TYPE_ALIASES.get(db_type.strip().lower())


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


# ===================== Oracle 实现（python-oracledb thin 模式，支持 12.1+） =====================

def _oracle_connect(host: str, port: int, user: str, password: str, database: str) -> Any:
    """建立 Oracle 只读连接（thin 模式，无需 Instant Client）。"""
    try:
        import oracledb
    except ImportError:
        raise ImportError("oracledb 库未安装。请执行: pip install python-oracledb")
    service = database or "ORCL"
    conn = oracledb.connect(user=user, password=password, dsn=f"{host}:{port}/{service}")
    try:
        cursor = conn.cursor()
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.close()
    except Exception as e:
        logger.warning("设置 Oracle 只读事务失败（建议使用只读账号）: %s", e)
    return conn


def _query_oracle(config: dict, sql: str) -> str:
    """执行Oracle查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    host = config.get("host", "localhost")
    port = int(config.get("port", 1521) or 1521)
    user = config.get("user", "")
    database = config.get("database", "")
    key = ("oracle", host, port, user, database)

    try:
        conn = _acquire(
            key,
            lambda: _oracle_connect(host, port, user, config.get("password", ""), database),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [d[0] for d in cursor.description]
                rows = [tuple(r) for r in cursor.fetchall()]
                cursor.close()
                if not rows:
                    return "查询结果：无匹配数据"
                result = _format_query_result(cols, rows)
                result.append(f"\n共 {len(rows)} 条记录")
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
        return f"【Oracle查询异常】{str(e)}"


# ===================== SQL Server 实现（pymssql） =====================

def _sqlserver_connect(host: str, port: int, user: str, password: str, database: str) -> Any:
    """建立 SQL Server 只读连接（只读依赖关键字黑名单 + 只读账号）。"""
    try:
        import pymssql
    except ImportError:
        raise ImportError("pymssql 库未安装。请执行: pip install pymssql")
    return pymssql.connect(
        server=host, port=str(port), user=user, password=password,
        database=database, charset="utf8", login_timeout=8,
    )


def _query_sqlserver(config: dict, sql: str) -> str:
    """执行SQL Server查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    host = config.get("host", "localhost")
    port = int(config.get("port", 1433) or 1433)
    user = config.get("user", "sa")
    database = config.get("database", "")
    key = ("sqlserver", host, port, user, database)

    try:
        conn = _acquire(
            key,
            lambda: _sqlserver_connect(host, port, user, config.get("password", ""), database),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [d[0] for d in cursor.description]
                rows = [tuple(r) for r in cursor.fetchall()]
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
        return f"【SQL Server查询异常】{str(e)}"


# ===================== 达梦 DM8 实现（dmPython） =====================

def _dm_connect(host: str, port: int, user: str, password: str, database: str) -> Any:
    """建立达梦只读连接。database 参数映射为达梦模式（SCHEMA）。"""
    try:
        import dmPython
    except ImportError:
        raise ImportError(
            "dmPython 驱动未安装（达梦数据库）。请在 requirements.txt 中保留 dmPython 并重建镜像"
        )
    kwargs: Dict[str, Any] = dict(user=user, password=password, server=host, port=port)
    schema = (database or "").strip()
    if schema:
        kwargs["schema"] = schema
    conn = dmPython.connect(**kwargs)
    try:
        cursor = conn.cursor()
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.close()
    except Exception as e:
        logger.warning("设置达梦只读事务失败（建议使用只读账号）: %s", e)
    return conn


def _query_dm(config: dict, sql: str) -> str:
    """执行达梦查询"""
    error = _sanitize_sql(sql)
    if error:
        return error

    host = config.get("host", "localhost")
    port = int(config.get("port", 5236) or 5236)
    user = config.get("user", "SYSDBA")
    database = config.get("database", "")
    key = ("dm", host, port, user, database)

    try:
        conn = _acquire(
            key,
            lambda: _dm_connect(host, port, user, config.get("password", ""), database),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(sql)

            if cursor.description:
                cols = [d[0] for d in cursor.description]
                rows = [tuple(r) for r in cursor.fetchall()]
                cursor.close()
                if not rows:
                    return "查询结果：无匹配数据"
                result = _format_query_result(cols, rows)
                result.append(f"\n共 {len(rows)} 条记录")
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
        return f"【达梦查询异常】{str(e)}"


# ===================== ClickHouse 实现（clickhouse-connect，HTTP 接口） =====================

def _ch_connect(host: str, port: int, user: str, password: str, database: str) -> Any:
    """建立 ClickHouse 连接（HTTP 8123）。"""
    try:
        import clickhouse_connect
    except ImportError:
        raise ImportError("clickhouse-connect 库未安装。请执行: pip install clickhouse-connect")
    return clickhouse_connect.get_client(
        host=host, port=port, username=user or "default",
        password=password, database=database or "default",
    )


def _query_clickhouse(config: dict, sql: str) -> str:
    """执行ClickHouse查询（客户端非 DB-API 连接，不走连接池，直连每次新建）。"""
    error = _sanitize_sql(sql)
    if error:
        return error

    host = config.get("host", "localhost")
    port = int(config.get("port", 8123) or 8123)
    user = config.get("user", "default")
    database = config.get("database", "")

    try:
        client = _ch_connect(host, port, user, config.get("password", ""), database)
        try:
            result = client.query(sql)
            cols = list(result.result_column_names)
            rows = [tuple(r) for r in result.result_rows]
            if not rows:
                return "查询结果：无匹配数据"
            formatted = _format_query_result(cols, rows)
            formatted.append(f"\n共 {len(rows)} 条记录")
            return "\n".join(formatted)
        finally:
            try:
                client.close()
            except Exception:
                pass

    except Exception as e:
        return f"【ClickHouse查询异常】{str(e)}"


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
            "支持: sqlite；MySQL 协议族 mysql/mariadb/tidb/oceanbase/tdsql/polardb/doris/starrocks；"
            "PostgreSQL 协议族 postgresql/kingbase(人大金仓)/opengauss/gaussdb/vastbase/highgo/oscar；"
            "以及 oracle、sqlserver、dm(达梦)、clickhouse。"
            "Args: name(连接名称), db_type(数据库类型,见上), "
            "host(主机地址), port(端口,0则用默认), user(用户名), password(密码), "
            "database(数据库名；SQLite 填文件绝对路径；达梦填模式名), extra_params(可选JSON额外参数), "
            "user_id(当前登录用户ID,默认default)"
        )
    )
    def db_register_connection(name: str, db_type: str, host: str = "localhost", port: int = 0,
                               user: str = "", password: str = "", database: str = "",
                               extra_params: str = "", user_id: str = "default") -> str:
        family = _normalize_db_type(db_type)
        if not family:
            return _validate_db_connection_type(db_type)

        name_err = _validate_identifier(name, "连接名称")
        if name_err:
            return name_err

        if not host:
            host = "localhost"

        # 端口默认值（按用户传入的原始别名匹配，如 kingbase→54321、dameng→5236）
        if port == 0:
            port = _DB_DEFAULT_PORTS.get(db_type.strip().lower(), 0)

        extra = {}
        if extra_params:
            try:
                extra = json.loads(extra_params)
            except json.JSONDecodeError:
                return "【错误】extra_params 不是有效的JSON格式"

        cfg = {
            "db_type": family,
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

        host_display = database if family == "sqlite" else f"{host}:{port}/{database}"
        return f"【已注册】连接 '{name}' ({family}:{host_display})"

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

        db_type = _normalize_db_type(config.get("db_type", "")) or config.get("db_type", "")
        try:
            if db_type == "sqlite":
                return _query_sqlite(config["database"], sql)
            elif db_type == "mysql":
                return _query_mysql(config, sql)
            elif db_type == "postgresql":
                return _query_postgresql(config, sql)
            elif db_type == "oracle":
                return _query_oracle(config, sql)
            elif db_type == "sqlserver":
                return _query_sqlserver(config, sql)
            elif db_type == "dm":
                return _query_dm(config, sql)
            elif db_type == "clickhouse":
                return _query_clickhouse(config, sql)
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

        family = _normalize_db_type(config.get("db_type", "")) or config.get("db_type", "")

        if family == "sqlite":
            return _get_table_schema_sqlite(config["database"], table_name)

        if family in ("oracle", "dm"):
            # Oracle / 达梦：user_tab_columns 数据字典（表名不区分大小写）
            sql = (
                "SELECT column_name, data_type, nullable, data_default "
                "FROM user_tab_columns WHERE UPPER(table_name) = UPPER("
                f"{_quote_literal(table_name)}) ORDER BY column_id"
            )
            try:
                return _query_oracle(config, sql) if family == "oracle" else _query_dm(config, sql)
            except Exception as e:
                return f"【获取表结构失败】{str(e)}"

        if family == "sqlserver":
            sql = (
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
                "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = "
                f"{_quote_literal(table_name)} ORDER BY ORDINAL_POSITION"
            )
            try:
                return _query_sqlserver(config, sql)
            except Exception as e:
                return f"【获取表结构失败】{str(e)}"

        if family == "clickhouse":
            try:
                return _query_clickhouse(config, f"DESCRIBE TABLE {_quote_ident(table_name, 'mysql')}")
            except Exception as e:
                return f"【获取表结构失败】{str(e)}"

        # MySQL/PostgreSQL 协议族通过查询 information_schema（表名走字面量转义）
        sql = (
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_name = "
            f"{_quote_literal(table_name)} ORDER BY ordinal_position"
        )
        try:
            if family == "mysql":
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
