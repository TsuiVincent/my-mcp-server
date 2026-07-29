# mcp-file-doc - 文件操作与文档智能处理 MCP Server

负责文件 I/O、远程传输、智能填表、Word 高级操作等功能。

> **注意**：Markitdown 格式转换已拆分到 [mcp-markitdown](../mcp-markitdown/) (端口 8007)，Excel 操作已迁移至 [mcp-spreadsheet-pdf](../mcp-spreadsheet-pdf/) (端口 8012)。

详细架构和跨服务器配置见 [根目录 README](../README.md)。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:8002`，使用 `streamable-http` 传输协议。

## 工具列表 (26个)

### 文件操作

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `file_read` | 读取文件内容 | `path` |
| `file_write` | 写入文件 | `path`, `content`, `append`(可选) |
| `file_edit` | 查找替换 | `path`, `old_string`, `new_string` |
| `dir_list` | 列出目录 | `path`(默认当前目录) |
| `dir_create` | 创建目录 | `path` |
| `read_json` | 读取JSON文件 | `path` |

### 远程文件传输

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `file_upload` | Base64上传文件到服务器 | `content_base64`, `filename` |
| `file_download` | Base64下载文件 | `path` |
| `file_list_uploads` | 列出已上传文件 | 无 |

### 智能填表

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `smart_fill_form_local` | 本地路径一站式智能填表（推荐，无大小限制） | `docx_path`, `knowledge_data`(可选), ... |
| `smart_fill_form` | Base64一站式智能填表（文件限制15MB） | `file_base64`, `filename`, `knowledge_data`(可选), ... |
| `parse_word_form` | 解析本地Word表单字段 | `docx_path` |
| `parse_word_form_base64` | 解析Base64 Word表单字段 | `file_base64`, `filename` |
| `read_knowledge_base` | 读取知识库JSON | `kb_path`, `kb_data`(可选) |
| `extract_personal_info_from_context` | 从知识库上下文提取结构化信息 | `context_text` |
| `read_personal_info_from_text` | 文本解析个人信息 | `text` |
| `read_personal_info_from_file` | 文件提取个人信息 | `file_path` |
| `merge_info_sources` | 合并多源信息 | `sources_json` |
| `fill_word_form` | 手动传入fill_data_json填表 | `docx_path`, `output_file`, `fill_data_json`, ... |
| `fill_word_form_base64` | 手动传入fill_data_json填表（Base64） | `file_base64`, `filename`, `fill_data_json`, ... |

### 文档创建与高级编辑

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `word_read` | 读取Word文档内容（段落/表格） | `path` |
| `word_create_doc` | 从零创建Word文档 | `text`, `filename`(可选), `font_name`, `font_size_pt`, ... |
| `word_add_paragraph` | 向已有文档追加段落 | `path`, `text`, `font_name`, `font_size_pt`, `font_color`, `bold`, `alignment` |
| `word_add_heading` | 向已有文档追加标题 | `path`, `text`, `level`, `font_name` |
| `word_add_table` | 向已有文档追加表格 | `path`, `data`(JSON), `headers`(JSON), `font_name`, `font_size_pt` |

## 智能填表工作流程

`file_upload` 和 `smart_fill_form_local` 在同一服务器，一次工具调用完成填表：

```
平台调用 file_upload 上传空表 → 获得 server_path
平台把 server_path 和知识库结果注入 LLM 上下文
LLM 调用 smart_fill_form_local(docx_path=server_path, knowledge_data="...")
    → 返回下载链接
```

### 字段匹配能力

- **五级匹配**：精确 → 规范化（去空格/标点） → 同义词 → 分词 → 包含
- **68 条内置同义词**：`出生年月`→`出生日期`、`联系电话`→`手机号码` 等
- **可扩展**：Docker 挂载 `config/field_synonyms.json` 自定义

## 平台配置

### Cherry Studio
```json
{
  "mcpServers": {
    "mcp-file-doc": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:8002/mcp"
    }
  }
}
```

### OpenCode
```json
{
  "mcpServers": {
    "mcp-file-doc": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:8002/mcp"
    }
  }
}
```

### Dify
- **协议类型**: Streamable HTTP
- **服务端点**: `http://<服务器IP>:8002/mcp`

### Cursor / Claude Desktop
```json
{
  "mcpServers": {
    "mcp-file-doc": {
      "type": "streamableHttp",
      "url": "http://<服务器IP>:8002/mcp"
    }
  }
}
```

## 依赖

```
mcp>=1.6.0
httpx>=0.27.0
uvicorn>=0.30.0
python-dotenv
python-docx>=1.1.0
```

## Docker 部署

Docker 容器运行在 Linux 环境，无法直接访问 Windows 宿主机的 `C:\Users\...` 路径。需要将宿主机目录挂载到容器内：

```yaml
# docker-compose.yml 已自动配置
environment:
  - HOST_DOWNLOADS=/mnt/host/downloads
  - HOST_DESKTOP=/mnt/host/desktop
  - HOST_DOCUMENTS=/mnt/host/documents
volumes:
  - ${USERPROFILE:-~}/Downloads:/mnt/host/downloads
  - ${USERPROFILE:-~}/Desktop:/mnt/host/desktop
  - ${USERPROFILE:-~}/Documents:/mnt/host/documents
```

**路径自动转换**：工具收到 `C:\Users\lx\Downloads\xxx.docx` 后，自动映射为 `/mnt/host/downloads/xxx.docx`。
