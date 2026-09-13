# My-MCP-Intranet - 内网 MCP 服务器集群

> v2.3 — 13 个独立 MCP Server，可按需部署在不同 IP 的服务器上，实现功能隔离与故障域分离。

## 架构概览

```
                     ┌──────────────────────────────────────────────────────────────────┐
                     │                         AI 客户端                              │
                     │  (CherryStudio / OpenCode / Dify / Cursor / Claude Desktop)    │
                     └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬───────────────────────────┘
                        │  │  │  │  │  │  │  │  │  │  │  │  │
        ┌───────────────┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼───────────────────────────┐
        │               │  │  │  │  │  │  │  │  │  │  │  │  │                           │
        ▼               ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼                           ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│mcp-markitdown│ │mcp-browser-  │ │mcp-sequential│ │mcp-data-     │ │mcp-datetime  │ │mcp-ops-      │
│   :19101      │ │playwright    │ │-thinking     │ │platform      │ │   :19105      │ │monitor       │
│              │ │   :19102      │ │   :19103      │ │   :19104      │ │              │ │   :19106      │
│ Markitdown   │ │ 浏览器自动化  │ │ 结构化推理   │ │ 数据库查询   │ │ 时间日期     │ │ 系统监控     │
│ 格式转换     │ │ 页面截图     │ │ 分步深度思考 │ │ Python沙箱   │ │ 时区转换     │ │ 日志分析     │
│ Markdown渲染 │ │ 元素交互     │ │ 回溯修正     │ │ 数据可视化   │ │ Cron解析     │ │ 命令执行     │
│              │ │ JS执行       │ │ 分支推理     │ │ 知识库检索   │ │              │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
    4 tools        14 tools         1 tool         21 tools         7 tools         13 tools

┌──────────────┐ ┌─────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ mcp-fetch-   │ │ ppt-master-mcp  │ │ mcp-drawio   │ │ mcp-form-fill│ │mcp-office-   │ │mcp-office-   │
│ intranet     │ │    :19108        │ │   :19110      │ │   :19120      │ │word          │ │excel         │
│    :19107     │ │                 │ │   :19111      │ │              │ │   :19121      │ │   :19122      │
│ 内网抓取     │ │ AI PPT 生成     │ │ AI 图表生成  │ │ 智能填表     │ │ Word 通用操作 │ │ Excel/CSV    │
│ 网页正文提取 │ │ AI 配图(16+)   │ │ Draw.io 编辑 │ │ Word+Excel   │ │ 文档读写创作 │ │ CRUD/分析     │
│ 递归爬取     │ │ 模板(20+)      │ │ 实时预览     │ │ 表单解析填充 │ │ 文件管理     │ │ 统计图表     │
│ 配置管理     │ │ SVG→PPTX       │ │              │ │              │ │              │ │              │
└──────────────┘ └─────────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
    19 tools        15 tools            6 tools          17 tools         14 tools         15 tools

┌──────────────┐
│mcp-office-pdf│
│   :19123      │
│              │
│ PDF 读取     │
│ 合并/拆分    │
│ 提取/创建    │
│ 文件管理     │
└──────────────┘
    9 tools
```

## 服务器总览

| 服务器 | 端口 | 工具数 | 核心功能 | 部署要求 |
|--------|------|--------|---------|---------|
| [mcp-markitdown](./mcp-markitdown/) | 19101 | 4 | Markitdown 格式转换、Markdown 渲染 | 需 markitdown |
| [mcp-browser-playwright](./mcp-browser-playwright/) | 19102 | 14 | **浏览器自动化**、页面截图、元素交互、JS 执行 | 需 Chromium |
| [mcp-sequential-thinking](./mcp-sequential-thinking/) | 19103 | 1 | **结构化多步推理**、回溯修正、分支推理 | 无 |
| [mcp-data-platform](./mcp-data-platform/) | 19104 | 21 | 数据库查询、Python沙箱、数据可视化、知识库检索 | 需数据库连接 |
| [mcp-datetime](./mcp-datetime/) | 19105 | 7 | 时间日期查询、时区转换、Cron解析 | 无 |
| [mcp-ops-monitor](./mcp-ops-monitor/) | 19106 | 13 | CPU/内存/磁盘监控、日志分析、命令执行 | 需部署在目标主机 |
| [mcp-fetch-intranet](./mcp-fetch-intranet/) | 19107 | 19 | 内网网页抓取、正文提取、递归爬取、配置管理 | 需内网可达 |
| [**ppt-master-mcp**](./ppt-master-mcp/) | **19108** | **15** | **AI PPT 生成与增强**、20+模板、AI配图(16+后端)、PPTX导出 | 需 ppt-master v4.2.0 |
| [mcp-drawio](./mcp-drawio/) | 19110/19111 | 6 | **AI Draw.io 图表生成**、实时预览、图库注入 | 需 Chromium |
| [**mcp-form-fill**](./mcp-form-fill/) | **19120** | **17** | **智能填表**（Word/Excel 表单解析、字段填充、信息提取） | 需 python-docx |
| [**mcp-office-word**](./mcp-office-word/) | **19121** | **14** | **Word 通用操作**（读写、段落/标题/表格创作）+ 文件管理 | 需 python-docx |
| [**mcp-office-excel**](./mcp-office-excel/) | **19122** | **15** | **Excel/CSV 通用操作**（CRUD、合并单元格、样式、统计） | 需 openpyxl |
| [**mcp-office-pdf**](./mcp-office-pdf/) | **19123** | **9** | **PDF 操作**（读取、合并、拆分、提取、创建）+ 文件管理 | 需 PyMuPDF |

## 快速启动

### Docker Compose 一键部署（推荐）

```bash
docker-compose up -d
```

启动单个服务：
```bash
docker-compose up -d mcp-office-word
docker-compose up -d mcp-browser-playwright
docker-compose up -d mcp-drawio
```

### 本地启动（开发调试）

先安装依赖：

```bash
cd my-mcp-intranet
pip install -r requirements.txt
```

再分别启动各服务器：

```bash
# 终端1 - Markitdown 格式转换
cd mcp-markitdown && python server.py

# 终端2 - 浏览器自动化 (Playwright)
cd mcp-browser-playwright && playwright install chromium && python server.py

# 终端3 - Sequential Thinking
cd mcp-sequential-thinking && python server.py

# 终端4 - 数据查询与分析
cd mcp-data-platform && python server.py

# 终端5 - 时间日期服务
cd mcp-datetime && python server.py

# 终端6 - 运维与监控
cd mcp-ops-monitor && python server.py

# 终端7 - 内网抓取与API
cd mcp-fetch-intranet && python server.py

# 终端8 - PPT Master
cd ppt-master-mcp && python server.py

# 终端9 - 智能填表
cd mcp-form-fill && python server.py

# 终端10 - Word 通用操作
cd mcp-office-word && python server.py

# 终端11 - Excel/CSV 通用操作
cd mcp-office-excel && python server.py

# 终端12 - PDF 操作
cd mcp-office-pdf && python server.py

# 终端13 - Draw.io 图表
cd mcp-drawio && python server.py
```

## 服务拆分说明（v2.2）

原 `mcp-file-doc` / `mcp-spreadsheet-pdf` 已按功能拆分为以下独立服务，实现故障隔离：

| 原服务 | 拆分出 | 端口 |
|--------|--------|------|
| mcp-file-doc | **mcp-form-fill**（智能填表） | 19120 |
| mcp-file-doc | **mcp-office-word**（Word 通用操作） | 19121 |
| mcp-spreadsheet-pdf | **mcp-office-excel**（Excel/CSV） | 19122 |
| mcp-spreadsheet-pdf | **mcp-office-pdf**（PDF 操作） | 19123 |

原 `mcp-file-doc`、`mcp-spreadsheet-pdf`、`mcp-mineru-bridge` 已下线。

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

### mcp-form-fill (:19120) - 智能填表（v2.2 新增）

从 mcp-file-doc / mcp-spreadsheet-pdf 拆分，专注 Word/Excel 表单解析与智能填充。

| 工具集 | 功能 |
|------|------|
| Word 填表（11） | 表单结构解析、字段定位、智能填充（含本地模型）、信息提取 |
| Excel 填表（3） | 表格解析、单元格填充、智能填充 |
| 文件传输（3） | 文件上传 / 下载 / 列表 |

### mcp-office-word (:19121) - Word 通用操作（v2.2 新增）

从 mcp-file-doc 拆分，专注 Word 文档读写与创作。

| 工具集 | 功能 |
|------|------|
| Word 操作（5） | 文档读取、创建、添加段落/标题/表格 |
| 通用文件（9） | 文件读写/编辑、目录管理、JSON、上传下载 |

### mcp-office-excel (:19122) - Excel/CSV 通用操作（v2.2 新增）

从 mcp-spreadsheet-pdf 拆分，专注表格数据操作。

| 工具集 | 功能 |
|------|------|
| Excel 操作（12） | 创建/读取/写入、单元格/行/列、合并、样式、多 Sheet |
| CSV 操作（3） | 读取 / 写入 / 分析 |

### mcp-office-pdf (:19123) - PDF 操作（v2.2 新增）

从 mcp-spreadsheet-pdf 拆分，专注 PDF 处理。

| 工具集 | 功能 |
|------|------|
| PDF 操作（6） | 文本读取、信息获取、合并、拆分、提取页、创建 |
| 文件传输（3） | 文件上传 / 下载 / 列表 |

## 客户端配置

### Cherry Studio / OpenCode / Cursor

```json
{
  "mcpServers": {
    "mcp-markitdown":             { "type": "streamableHttp", "url": "http://127.0.0.1:19101/mcp" },
    "mcp-browser-playwright":     { "type": "streamableHttp", "url": "http://127.0.0.1:19102/mcp" },
    "mcp-sequential-thinking":    { "type": "streamableHttp", "url": "http://127.0.0.1:19103/mcp" },
    "mcp-data-platform":          { "type": "streamableHttp", "url": "http://127.0.0.1:19104/mcp" },
    "mcp-datetime":               { "type": "streamableHttp", "url": "http://127.0.0.1:19105/mcp" },
    "mcp-ops-monitor":            { "type": "streamableHttp", "url": "http://127.0.0.1:19106/mcp" },
    "mcp-fetch-intranet":         { "type": "streamableHttp", "url": "http://127.0.0.1:19107/mcp" },
    "ppt-master-mcp":             { "type": "streamableHttp", "url": "http://127.0.0.1:19108/mcp" },
    "mcp-drawio":                 { "type": "streamableHttp", "url": "http://127.0.0.1:19110/mcp" },
    "mcp-form-fill":              { "type": "streamableHttp", "url": "http://127.0.0.1:19120/mcp" },
    "mcp-office-word":            { "type": "streamableHttp", "url": "http://127.0.0.1:19121/mcp" },
    "mcp-office-excel":           { "type": "streamableHttp", "url": "http://127.0.0.1:19122/mcp" },
    "mcp-office-pdf":             { "type": "streamableHttp", "url": "http://127.0.0.1:19123/mcp" }
  }
}
```

### Dify

| 服务器 | 协议 | 端点 |
|--------|------|------|
| mcp-markitdown | Streamable HTTP | `http://<IP>:19101/mcp` |
| mcp-browser-playwright | Streamable HTTP | `http://<IP>:19102/mcp` |
| mcp-sequential-thinking | Streamable HTTP | `http://<IP>:19103/mcp` |
| mcp-data-platform | Streamable HTTP | `http://<IP>:19104/mcp` |
| mcp-datetime | Streamable HTTP | `http://<IP>:19105/mcp` |
| mcp-ops-monitor | Streamable HTTP | `http://<IP>:19106/mcp` |
| mcp-fetch-intranet | Streamable HTTP | `http://<IP>:19107/mcp` |
| ppt-master-mcp | Streamable HTTP | `http://<IP>:19108/mcp` |
| mcp-drawio | Streamable HTTP | `http://<IP>:19110/mcp` |
| mcp-form-fill | Streamable HTTP | `http://<IP>:19120/mcp` |
| mcp-office-word | Streamable HTTP | `http://<IP>:19121/mcp` |
| mcp-office-excel | Streamable HTTP | `http://<IP>:19122/mcp` |
| mcp-office-pdf | Streamable HTTP | `http://<IP>:19123/mcp` |

## 设计原则

- **功能内聚**：每个服务器包含高内聚的工具集
- **故障隔离**：一个服务器故障不影响其他服务器
- **依赖分离**：重依赖（python-docx/markitdown/playwright/chromadb）的服务独立部署
- **安全分层**：`mcp-ops-monitor`（命令执行）和 `mcp-data-platform`（Python沙箱）可部署在加固容器中
- **独立扩展**：可对高频使用的服务器单独扩容

## 数据存储

| 服务器 | 存储方式 | 路径 |
|--------|---------|------|
| mcp-markitdown | 无持久化 | — |
| mcp-browser-playwright | 无持久化 | — |
| mcp-sequential-thinking | 内存（会话级） | — |
| mcp-data-platform | ChromaDB + SQLite | `~/mcp-user-data/` (Windows) `/data/mcp-user-data/` (Linux) |
| mcp-datetime | 无持久化 | — |
| mcp-ops-monitor | 无持久化 | — |
| mcp-fetch-intranet | SQLite | `~/mcp-user-data/config_manager.db` (Windows) `/data/mcp-user-data/config_manager.db` (Linux) |
| ppt-master-mcp | Docker Volume | `ppt_master_data:/app/workspaces` |
| mcp-drawio | Docker Volume | `drawio_data:/data` |
| mcp-form-fill | Docker Volume | `form_fill_data:/data` |
| mcp-office-word | Docker Volume | `office_word_data:/data` |
| mcp-office-excel | Docker Volume | `office_excel_data:/data` |
| mcp-office-pdf | Docker Volume | `office_pdf_data:/data` |

## 许可证

Internal use.
