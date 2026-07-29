# mcp-ops-monitor - 运维与监控 MCP Server

负责服务器资源监控、日志分析、命令行执行等功能，需部署在目标服务器上。

详细架构和跨服务器配置见 [根目录 README](../README.md)。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:8004`，使用 `streamable-http` 传输协议。

## 工具列表 (13个)

### 系统监控
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `monitor_cpu` | CPU使用率监控 | `interval`(可选,默认1秒) |
| `monitor_memory` | 内存使用监控 | 无 |
| `monitor_disk` | 磁盘空间监控 | `path`(可选) |
| `monitor_network` | 网络IO监控 | 无 |
| `monitor_processes` | 进程列表(按内存) | `top_n`(可选,默认10) |
| `monitor_system_info` | 系统信息汇总 | 无 |

### 日志分析
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `log_parse_file` | 解析日志文件 | `file_path` |
| `log_search_errors` | 搜索错误/异常 | `file_path` |
| `log_summary` | 日志摘要统计 | `file_path` |
| `log_tail` | 查看日志尾部 | `file_path`, `lines`(可选,默认20) |
| `log_filter` | 关键字过滤 | `file_path`, `keyword` |

### 命令执行
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `run_command` | 执行服务器命令 | `command`, `cwd`(可选), `timeout`(可选,默认30s) |
| `get_system_info` | 获取系统信息 | 无 |

## 平台配置

### Cherry Studio
```json
{
  "mcpServers": {
    "mcp-ops-monitor": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:8004/mcp"
    }
  }
}
```

### OpenCode
```json
{
  "mcpServers": {
    "mcp-ops-monitor": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:8004/mcp"
    }
  }
}
```

### Dify
- **协议类型**: Streamable HTTP
- **服务端点**: `http://<服务器IP>:8004/mcp`

### Cursor / Claude Desktop
```json
{
  "mcpServers": {
    "mcp-ops-monitor": {
      "type": "streamableHttp",
      "url": "http://<服务器IP>:8004/mcp"
    }
  }
}
```

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0, psutil
```

## 安全说明

- `run_command` 允许执行任意服务器命令，建议部署在受限容器中，并做好网络隔离
- 监控工具需 `psutil` 库支持
- 日志分析工具仅支持本地文件路径
