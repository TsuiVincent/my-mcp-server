# My-MCP-Intranet - 内网 MCP 服务器集群

> v2.0 — 11 个独立 MCP Server，可按需部署在不同 IP 的服务器上，实现功能隔离与故障域分离。

## 架构概览

```
                     ┌──────────────────────────────────────────────────────────────┐
                     │                         AI 客户端                              │
                     │  (CherryStudio / OpenCode / Dify / Cursor / Claude Desktop)    │
                     └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──────────────────────────────┘
                        │  │  │  │  │  │  │  │  │  │  │
        ┌───────────────┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──────────────────────────────┐
        │               │  │  │  │  │  │  │  │  │  │  │                              │
        ▼               ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼                              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ mcp-file-doc │ │mcp-markitdown│ │mcp-browser-  │ │mcp-sequential│ │mcp-data-     │ │mcp-datetime │
│   :19100      │ │   :19101      │ │playwright    │ │-thinking     │ │platform      │ │   :19105      │
│              │ │              │ │   :19102      │ │   :19103      │ │   :19104      │ │              │
│ 文件操作     │ │ Markitdown   │ │ 浏览器自动化  │ │ 结构化推理   │ │ 数据库查询   │ │ 时间日期     │
│ 远程传输     │ │ 格式转换     │ │ 页面截图     │ │ 分步深度思考 │ │ Python沙箱   │ │ 时区转换     │
│ 智能填表     │ │ Markdown渲染 │ │ 元素交互     │ │ 回溯修正     │ │ 数据可视化   │ │ Cron解析     │
│ Word高级操作 │ │              │ │ JS执行       │ │ 分支推理     │ │ 知识库检索   │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
    26 tools        4 tools        14 tools         1 tool         21 tools         7 tools

┌──────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐
│ mcp-ops-     │ │ mcp-fetch-      │ │ ppt-master-mcp  │ │ mcp-spread-  │ │ mcp-drawio   │
│ monitor      │ │ intranet        │ │    :19108        │ │ sheet-pdf    │ │   :19110      │
│   :19106      │ │    :19107        │ │                 │ │    :19109     │ │   :19111      │
│              │ │                 │ │ AI PPT 生成     │ │              │ │              │
│ 系统监控     │ │ 内网抓取        │ │ AI 配图(16+)   │ │ Excel 操作   │ │ AI 图表生成  │
│ 日志分析     │ │ 网页正文提取    │ │ 模板(20+)      │ │ CSV 处理     │ │ Draw.io 编辑 │
│ 命令执行     │ │ 配置管理        │ │ SVG→PPTX       │ │ PDF 操作     │ │ 实时预览     │
│              │ │                 │ │ PPTX 增强       │ │              │ │              │
└──────────────┘ └─────────────────┘ └─────────────────┘ └──────────────┘ └──────────────┘
    13 tools        19 tools            15 tools            14 tools          6 tools
```

## 服务器总览

| 服务器 | 端口 | 工具数 | 核心功能 | 部署要求 |
|--------|------|--------|---------|---------|
| [mcp-file-doc](./mcp-file-doc/) | 19100 | 26 | 文件 I/O、远程传输、**智能填表**、Word 高级操作 | 需 python-docx |
| [mcp-markitdown](./mcp-markitdown/) | 19101 | 4 | Markitdown 格式转换、Markdown 渲染 | 需 markitdown |
| [mcp-browser-playwright](./mcp-browser-playwright/) | 19102 | 14 | **浏览器自动化**、页面截图、元素交互、JS 执行 | 需 Chromium |
| [mcp-sequential-thinking](./mcp-sequential-thinking/) | 19103 | 1 | **结构化多步推理**、回溯修正、分支推理 | 无 |
| [mcp-data-platform](./mcp-data-platform/) | 19104 | 21 | 数据库查询、Python沙箱、数据可视化、知识库检索 | 需数据库连接 |
| [mcp-datetime](./mcp-datetime/) | **19105** | 7 | 时间日期查询、时区转换、Cron解析 | 无 |
| [mcp-ops-monitor](./mcp-ops-monitor/) | 19106 | 13 | CPU/内存/磁盘监控、日志分析、命令执行 | 需部署在目标主机 |
| [mcp-fetch-intranet](./mcp-fetch-intranet/) | 19107 | 19 | 内网网页抓取、正文提取、递归爬取、配置管理 | 需内网可达 |
| [**ppt-master-mcp**](./ppt-master-mcp/) | **19108** | **15** | **AI PPT 生成与增强**、20+模板、AI配图(16+后端)、PPTX导出 | 需 ppt-master v4.2.0 |
| [mcp-spreadsheet-pdf](./mcp-spreadsheet-pdf/) | 19109 | 14 | Excel/CSV/PDF 操作、统计图表、智能填表 | 需 PyMuPDF |
| [mcp-drawio](./mcp-drawio/) | 19110 | 6 | **AI Draw.io 图表生成**、实时预览、图库注入 | 需 Chromium |

## 快速启动

### 先安装全量依赖

```bash
cd my-mcp-intranet
pip install -r requirements.txt
```

### 再分别启动各服务器

```bash
# 终端1 - 文件操作 + 文档智能（填表/Word高级操作）
cd mcp-file-doc && python server.py

# 终端2 - Markitdown 格式转换
cd mcp-markitdown && python server.py

# 终端3 - 浏览器自动化 (Playwright)
cd mcp-browser-playwright && playwright install chromium && python server.py

# 终端4 - Sequential Thinking
cd mcp-sequential-thinking && python server.py

# 终端5 - 数据查询与分析
cd mcp-data-platform && python server.py

# 终端6 - 时间日期服务
cd mcp-datetime && python server.py

# 终端7 - 运维与监控
cd mcp-ops-monitor && python server.py

# 终端8 - 内网抓取与API
cd mcp-fetch-intranet && python server.py
```

### Docker Compose 一键部署

```bash
docker-compose up -d
```

启动单个服务：
```bash
docker-compose up -d mcp-browser-playwright
docker-compose up -d mcp-sequential-thinking
```

## 新增服务介绍

### mcp-browser-playwright (:19102) - 浏览器自动化

基于 Playwright + Chromium，支持内网后台自动化操作。

| 工具 | 功能 |
|------|------|
| `browser_navigate` | 导航到 URL |
| `browser_snapshot` | 获取页面无障碍结构快照 |
| `browser_screenshot` | 页面截图（Base64） |
| `browser_click` / `browser_type` / `browser_fill` | 元素交互 |
| `browser_select_option` / `browser_hover` | 下拉框/悬停 |
| `browser_press_key` | 按键（Enter/Tab/Escape） |
| `browser_evaluate` | 执行 JavaScript |
| `browser_get_page_text` | 获取页面文本 |
| `browser_go_back` / `browser_go_forward` | 前后导航 |
| `browser_close` | 关闭页面 |

### mcp-sequential-thinking (:19103) - 结构化推理

帮助 LLM 在复杂问题上分步深度思考，支持回溯修正和分支推理。

| 工具 | 功能 |
|------|------|
| `sequential_thinking` | 记录一步推理，支持修正、分支、会话保持 |

## 客户端配置

### Cherry Studio / OpenCode / Cursor

```json
{
  "mcpServers": {
    "mcp-file-doc":              { "type": "streamableHttp", "url": "http://127.0.0.1:19100/mcp" },
    "mcp-markitdown":             { "type": "streamableHttp", "url": "http://127.0.0.1:19101/mcp" },
    "mcp-browser-playwright":     { "type": "streamableHttp", "url": "http://127.0.0.1:19102/mcp" },
    "mcp-sequential-thinking":    { "type": "streamableHttp", "url": "http://127.0.0.1:19103/mcp" },
    "mcp-data-platform":          { "type": "streamableHttp", "url": "http://127.0.0.1:19104/mcp" },
    "mcp-datetime":               { "type": "streamableHttp", "url": "http://127.0.0.1:19105/mcp" },
    "mcp-ops-monitor":            { "type": "streamableHttp", "url": "http://127.0.0.1:19106/mcp" },
    "mcp-fetch-intranet":         { "type": "streamableHttp", "url": "http://127.0.0.1:19107/mcp" },
    "ppt-master-mcp":             { "type": "streamableHttp", "url": "http://127.0.0.1:19108/mcp" },
    "mcp-spreadsheet-pdf":        { "type": "streamableHttp", "url": "http://127.0.0.1:19109/mcp" },
    "mcp-drawio":                 { "type": "streamableHttp", "url": "http://127.0.0.1:19110/mcp" }
  }
}
```

### Dify

| 服务器 | 协议 | 端点 |
|--------|------|------|
| mcp-file-doc | Streamable HTTP | `http://<IP>:19100/mcp` |
| mcp-markitdown | Streamable HTTP | `http://<IP>:19101/mcp` |
| mcp-browser-playwright | Streamable HTTP | `http://<IP>:19102/mcp` |
| mcp-sequential-thinking | Streamable HTTP | `http://<IP>:19103/mcp` |
| mcp-data-platform | Streamable HTTP | `http://<IP>:19104/mcp` |
| mcp-datetime | Streamable HTTP | `http://<IP>:19105/mcp` |
| mcp-ops-monitor | Streamable HTTP | `http://<IP>:19106/mcp` |
| mcp-fetch-intranet | Streamable HTTP | `http://<IP>:19107/mcp` |
| ppt-master-mcp | Streamable HTTP | `http://<IP>:19108/mcp` |
| mcp-spreadsheet-pdf | Streamable HTTP | `http://<IP>:19109/mcp` |
| mcp-drawio | Streamable HTTP | `http://<IP>:19110/mcp` |

## 设计原则

- **功能内聚**：每个服务器包含高内聚的工具集
- **故障隔离**：一个服务器故障不影响其他服务器
- **依赖分离**：重依赖（python-docx/markitdown/playwright/chromadb）的服务独立部署
- **安全分层**：`mcp-ops-monitor`（命令执行）和 `mcp-data-platform`（Python沙箱）可部署在加固容器中
- **独立扩展**：可对高频使用的服务器单独扩容

## 数据存储

| 服务器 | 存储方式 | 路径 |
|--------|---------|------|
| mcp-file-doc | 本地文件系统 | `~/mcp-data/` (Windows) `/data/` (Linux) |
| mcp-markitdown | 无持久化 | — |
| mcp-browser-playwright | 无持久化 | — |
| mcp-sequential-thinking | 内存（会话级） | — |
| mcp-data-platform | ChromaDB + SQLite | `~/mcp-user-data/` (Windows) `/data/mcp-user-data/` (Linux) |
| mcp-datetime | 无持久化 | — |
| mcp-ops-monitor | 无持久化 | — |
| mcp-fetch-intranet | SQLite | `~/mcp-user-data/config_manager.db` (Windows) `/data/mcp-user-data/config_manager.db` (Linux) |
| ppt-master-mcp | Docker Volume | `ppt_master_data:/app/workspaces` |
| mcp-spreadsheet-pdf | Docker Volume | `spreadsheet_pdf_data:/data` |
| mcp-drawio | Docker Volume | `drawio_data:/data` |

## 许可证

Internal use.
