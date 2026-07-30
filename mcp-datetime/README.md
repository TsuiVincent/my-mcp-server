# mcp-datetime - 时间日期服务 MCP Server

从 `mcp-fetch-intranet` 拆分而来，独立承载时间日期处理功能（7个工具）。

详细架构和跨服务器配置见 [根目录 README](../README.md)。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:19105`，使用 `streamable-http` 传输协议。

## 工具列表 (7个)

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `time_current` | 获取当前时间（支持多时区） | `timezone`(可选,如 Asia/Shanghai) |
| `time_convert` | 时区转换 | `time_str`, `from_tz`, `to_tz` |
| `time_calculate` | 日期时间加减 | `base_time`, `operation`, `value`, `unit` |
| `time_format` | 格式化或解析时间 | `time_str`, `format_str`(可选) |
| `time_diff` | 计算时间差 | `time1`, `time2` |
| `time_list_timezones` | 列出常用时区 | 无 |
| `datetime_cron_parse` | Cron 表达式解析+下次执行时间 | `cron_expr` |

## 平台配置

### Cherry Studio
```json
{
  "mcpServers": {
    "mcp-datetime": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:19105/mcp"
    }
  }
}
```

### OpenCode
```json
{
  "mcpServers": {
    "mcp-datetime": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:19105/mcp"
    }
  }
}
```

### Dify
- **协议类型**: Streamable HTTP
- **服务端点**: `http://<服务器IP>:19105/mcp`

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0, python-dateutil, pytz
```
