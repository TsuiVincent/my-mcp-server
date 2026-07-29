"""
配置管理工具
提供集中式配置存储、版本控制与分发功能。支持INI/JSON/YAML/TOML等格式。
数据持久化到SQLite文件，重启不丢失。

工具列表：
- config_load: 加载配置文件
- config_get: 获取配置项
- config_set: 设置配置项
- config_save: 保存配置到文件
- config_list_namespaces: 列出所有配置命名空间
- config_diff: 对比配置版本差异
- config_export_all: 批量导出配置文件
"""

import os
import re
import json
import copy
import base64
import sqlite3
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ===================== SQLite 持久化存储 =====================

# 每个线程独立连接，保证线程安全
_local = threading.local()

# 最大历史版本数
_MAX_HISTORY = 10

# 数据库文件路径（在 register_config_manager_tools 时初始化）
_db_path: str = ""


def _get_conn() -> sqlite3.Connection:
    """获取当前线程的数据库连接（自动创建）"""
    if not hasattr(_local, "conn") or _local.conn is None:
        if not _db_path:
            raise RuntimeError("数据库未初始化，请先调用 register_config_manager_tools")
        os.makedirs(os.path.dirname(_db_path), exist_ok=True)
        _local.conn = sqlite3.connect(_db_path)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
    return _local.conn


def _init_db(db_path: str):
    """初始化数据库及表结构"""
    global _db_path
    _db_path = db_path
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS configs (
            namespace TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS config_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            namespace TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_namespace
        ON config_history(namespace)
    """)
    conn.commit()
    logger.info(f"配置数据库已初始化: {db_path}")


# ===================== 存储层操作（替代原来的 _config_store / _config_history 字典） =====================

def _db_get_config(namespace: str) -> Optional[dict]:
    """从数据库获取指定命名空间的配置"""
    row = _get_conn().execute(
        "SELECT data FROM configs WHERE namespace = ?", (namespace,)
    ).fetchone()
    return json.loads(row["data"]) if row else None


def _db_set_config(namespace: str, data: dict):
    """将配置写入数据库"""
    now = datetime.now().isoformat()
    data_json = json.dumps(data, ensure_ascii=False)
    _get_conn().execute(
        "INSERT OR REPLACE INTO configs (namespace, data, updated_at) VALUES (?, ?, ?)",
        (namespace, data_json, now)
    )
    _get_conn().commit()


def _db_delete_config(namespace: str):
    """删除命名空间配置"""
    _get_conn().execute("DELETE FROM configs WHERE namespace = ?", (namespace,))
    _get_conn().commit()


def _db_list_namespaces() -> list:
    """列出所有配置命名空间"""
    rows = _get_conn().execute(
        "SELECT namespace, updated_at FROM configs ORDER BY namespace"
    ).fetchall()
    return [(r["namespace"], r["updated_at"]) for r in rows]


def _db_add_history(namespace: str, data: dict):
    """添加配置历史版本"""
    timestamp = datetime.now().isoformat()
    data_json = json.dumps(data, ensure_ascii=False)
    conn = _get_conn()
    conn.execute(
        "INSERT INTO config_history (namespace, timestamp, data) VALUES (?, ?, ?)",
        (namespace, timestamp, data_json)
    )
    # 只保留最近 _MAX_HISTORY 条
    conn.execute("""
        DELETE FROM config_history WHERE id IN (
            SELECT id FROM config_history WHERE namespace = ?
            ORDER BY id DESC LIMIT -1 OFFSET ?
        )
    """, (namespace, _MAX_HISTORY))
    conn.commit()


def _db_get_history(namespace: str) -> list:
    """获取命名空间的历史版本列表"""
    rows = _get_conn().execute(
        "SELECT timestamp, data FROM config_history WHERE namespace = ? ORDER BY id ASC",
        (namespace,)
    ).fetchall()
    return [{"timestamp": r["timestamp"], "data": json.loads(r["data"])} for r in rows]


# ===================== 配置解析 =====================

# 支持的配置文件格式
_SUPPORTED_FORMATS = {
    ".json": "json",
    ".ini": "ini",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".conf": "ini",
    ".cfg": "ini",
}


def _parse_json(content: str) -> dict:
    """解析JSON"""
    return json.loads(content)


def _parse_ini(content: str) -> dict:
    """解析INI配置"""
    import configparser
    parser = configparser.ConfigParser()
    parser.read_string(content)
    result = {}
    for section in parser.sections():
        result[section] = dict(parser.items(section))
    if parser.defaults():
        result["DEFAULT"] = dict(parser.defaults())
    return result


def _parse_yaml(content: str) -> dict:
    """解析YAML"""
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        raise ImportError("yaml 库未安装。请执行: pip install pyyaml")


def _parse_toml(content: str) -> dict:
    """解析TOML"""
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            raise ImportError("toml 库未安装。请执行: pip install tomli (Python <3.11)")

    return tomllib.loads(content)


def _parse_config_content(content: str, fmt: str) -> dict:
    """根据格式解析配置内容"""
    parsers = {
        "json": _parse_json,
        "ini": _parse_ini,
        "yaml": _parse_yaml,
        "toml": _parse_toml,
    }
    parser = parsers.get(fmt)
    if parser is None:
        raise ValueError(f"不支持的配置格式: {fmt}")
    return parser(content)


# ===================== 配置导出 =====================

def _dump_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _dump_ini(data: dict) -> str:
    import configparser
    parser = configparser.ConfigParser()
    for section, items in data.items():
        parser[section] = {str(k): str(v) for k, v in items.items()}
    import io
    buf = io.StringIO()
    parser.write(buf)
    return buf.getvalue()


def _dump_yaml(data: dict) -> str:
    try:
        import yaml
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)
    except ImportError:
        raise ImportError("yaml 库未安装")


def _dump_toml(data: dict) -> str:
    try:
        import tomli_w
        return tomli_w.dumps(data)
    except ImportError:
        raise ImportError("tomli_w 库未安装。请执行: pip install tomli-w")


def _dump_config(data: dict, fmt: str) -> str:
    """根据格式导出配置"""
    dumpers = {
        "json": _dump_json,
        "ini": _dump_ini,
        "yaml": _dump_yaml,
        "toml": _dump_toml,
    }
    dumper = dumpers.get(fmt)
    if dumper is None:
        raise ValueError(f"不支持的导出格式: {fmt}")
    return dumper(data)


# ===================== 配置操作 =====================

def _snapshot_config(namespace: str):
    """创建当前配置的快照到历史表"""
    data = _db_get_config(namespace)
    if data is not None:
        _db_add_history(namespace, copy.deepcopy(data))


def _load_config(namespace: str, file_path: str) -> str:
    """从文件加载配置到指定命名空间"""
    if not os.path.exists(file_path):
        return f"【错误】文件不存在: {file_path}"

    ext = os.path.splitext(file_path)[1].lower()
    fmt = _SUPPORTED_FORMATS.get(ext)
    if fmt is None:
        return f"【错误】不支持的配置文件格式: {ext}。支持: {list(_SUPPORTED_FORMATS.keys())}"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="gbk") as f:
                content = f.read()
        except Exception as e:
            return f"【读取失败】{str(e)}"

    try:
        new_data = _parse_config_content(content, fmt)
        _snapshot_config(namespace)
        _db_set_config(namespace, new_data)
        key_count = len(_get_all_keys(new_data))
        return (
            f"【配置已加载】\n"
            f"  命名空间: {namespace}\n"
            f"  文件: {file_path}\n"
            f"  格式: {fmt}\n"
            f"  配置项数量: {key_count}"
        )
    except Exception as e:
        return f"【解析失败】{str(e)}"


def _load_config_from_base64(namespace: str, content_base64: str, filename: str) -> str:
    """从 Base64 编码的文件内容加载配置到命名空间（远程场景用）"""
    ext = os.path.splitext(filename)[1].lower()
    fmt = _SUPPORTED_FORMATS.get(ext)
    if fmt is None:
        return f"【错误】不支持的配置文件格式: {ext}。支持: {list(_SUPPORTED_FORMATS.keys())}"

    try:
        raw = base64.b64decode(content_base64)
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = raw.decode("gbk")
        except Exception as e:
            return f"【读取失败】无法解码: {str(e)}"
    except Exception as e:
        return f"【读取失败】Base64 解码失败: {str(e)}"

    try:
        new_data = _parse_config_content(content, fmt)
        _snapshot_config(namespace)
        _db_set_config(namespace, new_data)
        key_count = len(_get_all_keys(new_data))
        return (
            f"【配置已加载】\n"
            f"  命名空间: {namespace}\n"
            f"  源文件: {filename}\n"
            f"  格式: {fmt}\n"
            f"  配置项数量: {key_count}"
        )
    except Exception as e:
        return f"【解析失败】{str(e)}"


def _get_config(namespace: str, key: str = "") -> str:
    """获取配置项"""
    data = _db_get_config(namespace)
    if data is None:
        namespaces = _db_list_namespaces()
        ns_list = [ns for ns, _ in namespaces]
        return f"【提示】命名空间 '{namespace}' 不存在。可用: {ns_list}"

    if not key:
        return json.dumps(data, ensure_ascii=False, indent=2)

    # 支持点号分隔的嵌套键: "section.key"
    keys = key.split(".")
    current = data
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, "NOT_FOUND")
        else:
            return f"【错误】'{key}' 在 '{namespace}' 中不可用 (中间节点不是字典)"

    if current == "NOT_FOUND":
        return f"【提示】键 '{key}' 在命名空间 '{namespace}' 中不存在"

    if isinstance(current, (dict, list)):
        return json.dumps(current, ensure_ascii=False, indent=2)
    return str(current)


def _set_config(namespace: str, key: str, value: str) -> str:
    """设置配置项"""
    data = _db_get_config(namespace)
    if data is None:
        data = {}

    # 解析值类型
    parsed_value = _auto_parse_value(value)

    # 支持嵌套设置
    keys = key.split(".")
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]

    _snapshot_config(namespace)
    current[keys[-1]] = parsed_value
    _db_set_config(namespace, data)
    return f"【已设置】{namespace}.{key} = {parsed_value}"


def _auto_parse_value(value: str):
    """自动解析值的类型"""
    # bool
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    # null
    if value.lower() in ("null", "none"):
        return None
    # int
    try:
        return int(value)
    except ValueError:
        pass
    # float
    try:
        return float(value)
    except ValueError:
        pass
    # list (JSON)
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    return value


def _get_all_keys(data: dict, prefix: str = "") -> list:
    """获取所有配置键"""
    keys = []
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_get_all_keys(v, full_key))
        else:
            keys.append(full_key)
    return keys


def _save_config(namespace: str, file_path: str, fmt: str = "") -> str:
    """保存配置到文件"""
    data = _db_get_config(namespace)
    if data is None:
        return f"【错误】命名空间 '{namespace}' 不存在"

    if not fmt:
        ext = os.path.splitext(file_path)[1].lower()
        fmt = _SUPPORTED_FORMATS.get(ext, "json")

    try:
        content = _dump_config(data, fmt)
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"【已保存】{namespace} -> {file_path} ({fmt})"
    except Exception as e:
        return f"【保存失败】{str(e)}"


def _list_namespaces() -> str:
    """列出所有配置命名空间"""
    namespaces = _db_list_namespaces()
    if not namespaces:
        return "【提示】暂无配置命名空间"

    lines = ["【配置命名空间】"]
    for ns, updated_at in namespaces:
        data = _db_get_config(ns)
        key_count = len(_get_all_keys(data)) if data else 0
        history_count = len(_db_get_history(ns))
        lines.append(f"  {ns}: {key_count} 个配置项, {history_count} 个历史版本 (更新于 {updated_at})")
    return "\n".join(lines)


def _diff_config(namespace: str, version1: int = -2,
                  version2: int = -1) -> str:
    """对比两个配置版本"""
    history = _db_get_history(namespace)
    if not history:
        return f"【提示】命名空间 '{namespace}' 无历史版本"

    try:
        v1 = history[version1]
        v2 = history[version2]
    except IndexError:
        return f"【错误】版本索引越界，可用范围: {-len(history)} ~ {-1}"

    data1 = v1["data"]
    data2 = v2["data"]
    ts1 = v1["timestamp"]
    ts2 = v2["timestamp"]

    keys1 = set(_get_all_keys(data1))
    keys2 = set(_get_all_keys(data2))

    added = keys2 - keys1
    removed = keys1 - keys2
    modified = []

    for key in keys1 & keys2:
        val1 = _deep_get(data1, key)
        val2 = _deep_get(data2, key)
        if val1 != val2:
            modified.append((key, val1, val2))

    lines = [f"【配置差异: {namespace}】",
             f"版本1: {ts1}",
             f"版本2: {ts2}"]

    if added:
        lines.append(f"\n新增 ({len(added)}):")
        for key in sorted(added):
            lines.append(f"  + {key} = {_deep_get(data2, key)}")

    if removed:
        lines.append(f"\n删除 ({len(removed)}):")
        for key in sorted(removed):
            lines.append(f"  - {key}")

    if modified:
        lines.append(f"\n修改 ({len(modified)}):")
        for key, old, new in modified:
            lines.append(f"  ~ {key}: {old} -> {new}")

    if not added and not removed and not modified:
        lines.append("\n配置无变化")

    return "\n".join(lines)


def _deep_get(data: dict, key: str):
    """获取嵌套键值"""
    current = data
    for k in key.split("."):
        if isinstance(current, dict):
            current = current.get(k, "N/A")
        else:
            return "N/A"
    return current


def _export_configs(output_dir: str, fmt: str = "json") -> str:
    """批量导出所有配置"""
    namespaces = _db_list_namespaces()
    if not namespaces:
        return "【提示】暂无配置可导出"

    os.makedirs(output_dir, exist_ok=True)
    exported = []

    for ns, _updated_at in namespaces:
        data = _db_get_config(ns)
        if data is None:
            continue
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', ns)
        file_path = os.path.join(output_dir, f"{safe_name}.{fmt}")
        try:
            content = _dump_config(data, fmt)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            exported.append(file_path)
        except Exception as e:
            exported.append(f"失败: {ns} - {str(e)}")

    return (
        f"【批量导出完成】\n"
        f"  目录: {output_dir}\n"
        f"  格式: {fmt}\n"
        f"  文件:\n    " + "\n    ".join(exported)
    )


# ===================== 注册函数 =====================

def register_config_manager_tools(mcp, base_dir: str = ""):
    """
    注册配置管理工具到 MCP 服务器
    :param base_dir: 数据根目录，SQLite 数据库将存储在 base_dir/config_manager.db
    """
    # 初始化SQLite数据库
    if not base_dir:
        home = os.path.expanduser("~")
        db_path = os.path.join(home, ".config-mcp", "config.db")
    else:
        db_path = os.path.join(base_dir, "config_manager.db")
    _init_db(db_path)

    @mcp.tool(
        name="config_load",
        description="加载配置文件(.json/.ini/.yaml/.toml)到指定命名空间。Args: namespace(命名空间名称,必填), file_path(配置文件路径,必填)"
    )
    def config_load(namespace: str, file_path: str) -> str:
        return _load_config(namespace, file_path)

    @mcp.tool(
        name="config_load_base64",
        description="从Base64编码的文件内容加载配置到命名空间（远程服务器无法访问客户端文件时使用）。Args: namespace(命名空间,必填), content_base64(配置文件内容的Base64编码,必填), filename(文件名如config.json/pars.ini/settings.yaml,必填)"
    )
    def config_load_base64(namespace: str, content_base64: str, filename: str) -> str:
        return _load_config_from_base64(namespace, content_base64, filename)

    @mcp.tool(
        name="config_get",
        description="获取指定命名空间中的配置项。支持点号分隔的嵌套键。Args: namespace(命名空间,必填), key(配置键,支持section.key,留空获取全部)"
    )
    def config_get(namespace: str, key: str = "") -> str:
        return _get_config(namespace, key)

    @mcp.tool(
        name="config_set",
        description="设置配置项(自动识别bool/int/float/str类型)。支持点号分隔嵌套。Args: namespace(命名空间,必填), key(配置键,必填), value(配置值,必填)"
    )
    def config_set(namespace: str, key: str, value: str) -> str:
        return _set_config(namespace, key, value)

    @mcp.tool(
        name="config_save",
        description="将命名空间配置保存到服务器文件，并返回Base64编码内容供客户端下载。Args: namespace(命名空间,必填), file_path(服务器保存路径,必填), fmt(格式:json/ini/yaml/toml,可选,默认根据扩展名判断)"
    )
    def config_save(namespace: str, file_path: str, fmt: str = "") -> str:
        result = _save_config(namespace, file_path, fmt)
        data = _db_get_config(namespace)
        if data is not None:
            if not fmt:
                ext = os.path.splitext(file_path)[1].lower()
                fmt_out = _SUPPORTED_FORMATS.get(ext, "json")
            else:
                fmt_out = fmt
            content = _dump_config(data, fmt_out)
            b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
            return json.dumps({
                "message": result,
                "format": fmt_out,
                "download_base64": b64,
                "usage": "将 download_base64 解码后保存为 .{fmt} 文件",
            }, ensure_ascii=False, indent=2)
        return result

    @mcp.tool(
        name="config_list_namespaces",
        description="列出所有配置命名空间及版本信息"
    )
    def config_list_namespaces() -> str:
        return _list_namespaces()

    @mcp.tool(
        name="config_diff",
        description="对比配置版本差异。Args: namespace(命名空间,必填), version1(版本1索引,默认-2倒数第二版), version2(版本2索引,默认-1最新版)"
    )
    def config_diff(namespace: str, version1: int = -2,
                    version2: int = -1) -> str:
        return _diff_config(namespace, version1, version2)

    @mcp.tool(
        name="config_export_all",
        description="批量导出所有配置，同时保存到服务器并返回Base64编码内容。Args: output_dir(服务器输出目录,必填), fmt(导出格式:json/ini/yaml/toml,默认json)"
    )
    def config_export_all(output_dir: str, fmt: str = "json") -> str:
        result = _export_configs(output_dir, fmt)
        # 同时返回所有配置的 Base64 编码
        namespaces = _db_list_namespaces()
        files_b64 = {}
        for ns, _updated_at in namespaces:
            data = _db_get_config(ns)
            if data:
                content = _dump_config(data, fmt)
                files_b64[ns] = {
                    "filename": f"{ns}.{fmt}",
                    "base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                }
        return json.dumps({
            "server_result": result,
            "exported_files": files_b64,
            "usage": "每个 exported_files 的 base64 解码后保存为对应 filename",
        }, ensure_ascii=False, indent=2)

    logger.info("配置管理工具已注册 (SQLite持久化)")
