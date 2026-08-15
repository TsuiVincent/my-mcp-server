# mcp-mineru-bridge - MinerU 文档解析 MCP 桥接服务器

## 简介

轻量级 MCP 桥接服务器，将已有的 MinerU 服务（Docker 部署的 FastAPI 或云端 API）包装为 MCP 工具。无需本地 GPU 和模型文件，通过 HTTP 调用远程 MinerU 服务完成文档解析。

## 配置方式

### 方式一：创建 .env 文件（推荐）

在 `mcp-mineru-bridge` 目录下创建 `.env` 文件（可参考 `.env.example`）：

```ini
# MinerU MCP Bridge 配置

# 远程 MinerU API 地址（必填）
# 本地 Docker: http://host.docker.internal:8000
# 远程服务器: http://192.168.1.100:8000
# 云端 API:  https://mineru.net/api/v4
MINERU_API_URL=http://localhost:8000

# MinerU API 密钥（可选，云端 API 需要）
MINERU_API_KEY=
```

### 方式二：通过环境变量直接设置

```bash
# Windows (PowerShell)
$env:MINERU_API_URL="http://192.168.1.100:8000"
$env:MINERU_API_KEY=""
python server.py

# Windows (CMD)
set MINERU_API_URL=http://192.168.1.100:8000
set MINERU_API_KEY=
python server.py

# Linux / Mac
export MINERU_API_URL=http://192.168.1.100:8000
export MINERU_API_KEY=
python server.py
```

### 方式三：Docker Compose 部署时配置

在 `docker-compose.yml` 所在目录创建 `.env` 文件：

```ini
# 指向远程 MinerU API 地址
MINERU_API_URL=http://192.168.1.100:8000
# 如果有 API Key
MINERU_API_KEY=
```

然后启动：

```bash
docker-compose up -d mcp-mineru-bridge
```

## 典型场景配置示例

### 场景一：对接本地 Docker 部署的 MinerU

```ini
MINERU_API_URL=http://host.docker.internal:8000
```

> `host.docker.internal` 是 Docker 容器内访问宿主机的特殊域名。

### 场景二：对接远程服务器上的 MinerU

```ini
MINERU_API_URL=http://192.168.1.100:8000
```

### 场景三：对接 MinerU 云端 API

```ini
MINERU_API_URL=https://mineru.net/api/v4
MINERU_API_KEY=your_api_token_here
```

> Token 从 https://mineru.net/apiManage/token 获取。

## 工具列表

| 工具 | 功能 |
|------|------|
| `parse_document` | 上传文档解析为 Markdown（支持 PDF/图片/DOCX/PPTX/XLSX） |
| `parse_document_async` | 异步提交大文件解析任务，返回 task_id |
| `get_task_status` | 查询异步任务状态和进度 |
| `get_task_result` | 获取异步任务解析结果 |
| `ping` | 检测远程 MinerU 服务连通性 |

## 本地启动

```bash
cd mcp-mineru-bridge
pip install -r requirements.txt
# 别忘了先配置 MINERU_API_URL（通过 .env 或环境变量）
python server.py
```

## MCP 客户端配置

```json
{
  "mcpServers": {
    "mcp-mineru-bridge": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:19112/mcp"
    }
  }
}
```