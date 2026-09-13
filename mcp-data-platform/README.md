# mcp-data-platform - 数据查询与分析 MCP Server

负责数据库查询、Python沙箱执行、数据可视化、知识库检索等功能。

详细架构和跨服务器配置见 [根目录 README](../README.md)。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:19104`，使用 `streamable-http` 传输协议。

## 工具列表 (21个)

### 用户知识库
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `user_private_sql_query` | 用户私有SQL查询 | `sql` |
| `user_private_rag_search` | 用户私有RAG检索 | `query`, `top_k`(可选) |

### 数据库管理
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `db_register_connection` | 注册数据库连接 | `name`, `db_type`, `db_path`/`host`/`port`/`user`/`password`/`database` |
| `db_execute_query` | 执行SQL查询(只读) | `connection_name`, `sql` |
| `db_get_table_schema` | 获取表结构 | `connection_name`, `table_name` |
| `db_get_table_stats` | 表数据统计 | `connection_name`, `table_name` |
| `db_list_connections` | 列出所有连接 | 无 |

**支持数据库（按协议/驱动族归一，类型别名注册）：**

| 驱动族 | db_type 别名 | 驱动 |
|--------|--------------|------|
| SQLite | `sqlite` | 内置 sqlite3（mode=ro 只读） |
| MySQL 族 | `mysql` `mariadb` `tidb` `oceanbase` `tdsql` `polardb` `doris` `starrocks` | pymysql |
| PostgreSQL 族 | `postgresql` `kingbase`(人大金仓) `opengauss` `gaussdb` `vastbase` `highgo`(瀚高) `oscar`(神通) | psycopg2-binary |
| Oracle | `oracle`（12.1+，thin 模式） | python-oracledb |
| SQL Server | `sqlserver` `mssql` | pymssql |
| 达梦 DM8 | `dm` `dameng` | dmPython |
| ClickHouse | `clickhouse` `ch` | clickhouse-connect |

只读强制：SQLite `mode=ro` + `query_only`；MySQL/PG 会话只读；Oracle/达梦只读事务；全族统一 SQL 关键字黑名单（禁止 DROP/ALTER/INSERT/DELETE/UPDATE/CREATE/TRUNCATE/GRANT/EXEC/ATTACH 等）。

### Python代码执行
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `python_check_syntax` | 语法检查 | `code` |
| `python_exec_safe` | 安全沙箱执行 | `code` |
| `python_exec_json` | 执行并返回JSON | `code` |

### 数据可视化
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `viz_line_chart` | 折线图SVG | `data`(JSON), `title`, `theme`(可选) |
| `viz_bar_chart` | 柱状图SVG | `data`, `title`, `theme`(可选) |
| `viz_pie_chart` | 饼图SVG | `data`, `title`, `theme`(可选) |
| `viz_scatter_chart` | 散点图SVG | `data`, `title`, `theme`(可选) |
| `viz_create_report` | 多图表报表 | `charts`(JSON), `report_title`, `theme`(可选) |
| `viz_svg_to_file` | SVG保存+返回Base64 | `svg_content`, `file_path` |

### 知识库检索
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `kb_index_directory` | 索引目录 | `directory` |
| `kb_search` | 关键词搜索 | `query` |
| `kb_search_with_context` | 带上下文搜索 | `query` |
| `kb_list_documents` | 列出已索引文档 | 无 |
| `kb_clear_index` | 清空索引 | 无 |

## 平台配置

### Cherry Studio
```json
{
  "mcpServers": {
    "mcp-data-platform": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:19104/mcp"
    }
  }
}
```

### OpenCode
```json
{
  "mcpServers": {
    "mcp-data-platform": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:19104/mcp"
    }
  }
}
```

### Dify
- **协议类型**: Streamable HTTP
- **服务端点**: `http://<服务器IP>:19104/mcp`

### Cursor / Claude Desktop
```json
{
  "mcpServers": {
    "mcp-data-platform": {
      "type": "streamableHttp",
      "url": "http://<服务器IP>:19104/mcp"
    }
  }
}
```

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0, matplotlib, pymysql, psycopg2-binary
chromadb, sentence-transformers
```

## 安全说明

- Python沙箱限制：仅允许白名单模块(`math`, `json`, `datetime`等)，禁止 `exec`/`eval`/`open`/`__import__`
- SQL查询仅允许只读操作(`SELECT`/`SHOW`/`DESCRIBE`/`EXPLAIN`)，`INSERT`/`UPDATE`/`DELETE`/`DROP` 被拦截
