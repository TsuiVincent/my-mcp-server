# mcp-fetch-intranet - 内网抓取与API网关 MCP Server

负责内网网页抓取（含正文提取/递归爬取/URL发现）、内网API调用、配置管理等功能，可部署在内网任意节点。

详细架构和跨服务器配置见 [根目录 README](../README.md)。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

配置数据库自动创建在数据根目录 `config_manager.db`（SQLite持久化）。

默认监听 `http://0.0.0.0:8005`，使用 `streamable-http` 传输协议。

## 工具列表 (19个)

### 内网API调用
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `api_get` | 内网GET请求 | `endpoint`, `params`(可选JSON) |
| `api_post` | 内网POST请求 | `endpoint`, `data`(JSON), `headers`(可选JSON) |
| `query_erp_user` | 查询ERP用户 | `user_id` |
| `create_ticket` | 创建工单 | `title`, `content`, `priority`(可选) |

### 内网网页抓取
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `intranet_fetch_html` | 抓取网页HTML | `url`(限内网地址) |
| `intranet_fetch_content` | **抓取并提取正文**（自动去导航/广告/侧边栏） | `url`(限内网地址) |
| `intranet_crawl` | **递归爬取站内页面**，汇总正文 | `url`, `max_depth`(可选,3), `max_pages`(可选,50) |
| `intranet_map_urls` | **发现站点所有URL**（sitemap优先，降级首页链接） | `url`(限内网地址) |
| `intranet_extract_links` | 提取页面链接 | `html` |
| `intranet_download_resource` | 下载资源+返回Base64 | `url`, `save_dir`(可选) |
| `intranet_fetch_json` | 抓取JSON数据 | `url`(限内网地址) |



### 配置管理 (SQLite持久化)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `config_load` | 加载配置文件 | `namespace`, `file_path` |
| `config_load_base64` | Base64远程加载配置 | `namespace`, `content_base64`, `filename` |
| `config_get` | 获取配置项 | `namespace`, `key`(可选,支持嵌套) |
| `config_set` | 设置配置项 | `namespace`, `key`, `value` |
| `config_save` | 保存+返回Base64 | `namespace`, `file_path`, `fmt`(可选) |
| `config_list_namespaces` | 列出命名空间 | 无 |
| `config_diff` | 版本差异对比 | `namespace`, `version1`(可选), `version2`(可选) |
| `config_export_all` | 批量导出+返回Base64 | `output_dir`, `fmt`(可选) |

## 平台配置

### Cherry Studio
```json
{
  "mcpServers": {
    "mcp-fetch-intranet": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:8005/mcp"
    }
  }
}
```

### OpenCode
```json
{
  "mcpServers": {
    "mcp-fetch-intranet": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:8005/mcp"
    }
  }
}
```

### Dify
- **协议类型**: Streamable HTTP
- **服务端点**: `http://<服务器IP>:8005/mcp`

### Cursor / Claude Desktop
```json
{
  "mcpServers": {
    "mcp-fetch-intranet": {
      "type": "streamableHttp",
      "url": "http://<服务器IP>:8005/mcp"
    }
  }
}
```

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0
```

## 数据持久化

- 配置数据存储在 SQLite 数据库：Windows `%USERPROFILE%/mcp-user-data/config_manager.db`，Linux `/data/mcp-user-data/config_manager.db`
- 进程重启数据不丢失，支持最多10个历史版本
