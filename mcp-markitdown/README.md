# mcp-markitdown - Markitdown 格式转换 MCP Server

负责 Markitdown 格式转换、Markdown 渲染等功能。独立承载文档转换工具（4个）。

详细架构和跨服务器配置见 [根目录 README](../README.md)。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:19101`，使用 `streamable-http` 传输协议。

## 工具列表 (4个)

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `markitdown_convert_file` | 文件转Markdown（PDF/Word/Excel/PPT/HTML/CSV/JSON/XML等） | `file_path` |
| `markitdown_convert_url` | 内网URL转Markdown（仅限内网地址） | `url` |
| `markitdown_render_html` | Markdown渲染为HTML | `markdown_text` |
| `markitdown_supported_formats` | 列出支持格式 | 无 |

### 支持的文件格式

- **文档**: PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx)
- **网页**: HTML (.html, .htm)
- **数据**: CSV (.csv), JSON (.json), XML (.xml)
- **多媒体**: 图片 (OCR提取文字), 音频 (语音转文字)
- **归档**: ZIP (压缩包内文件)

## 平台配置

### Cherry Studio
```json
{
  "mcpServers": {
    "mcp-markitdown": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:19101/mcp"
    }
  }
}
```

### OpenCode
```json
{
  "mcpServers": {
    "mcp-markitdown": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:19101/mcp"
    }
  }
}
```

### Dify
- **协议类型**: Streamable HTTP
- **服务端点**: `http://<服务器IP>:19101/mcp`

### Cursor / Claude Desktop
```json
{
  "mcpServers": {
    "mcp-markitdown": {
      "type": "streamableHttp",
      "url": "http://<服务器IP>:19101/mcp"
    }
  }
}
```

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0, markitdown, markdown
```
