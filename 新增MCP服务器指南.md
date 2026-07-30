# 新增 MCP Server 操作指南

> 以「地震预警 API」为例，演示如何将任意外部 API 封装为项目的 MCP Server。

---

## 一、项目结构速览

```
my-mcp-server/
├── docker-compose.yml          ← 注册新服务
├── .env                        ← 全局环境变量（API Key 等）
├── 新增MCP服务器指南.md        ← 本文档
│
├── mcp-datetime/               ← 最简单模板（无外部 API，纯 Python）
│   ├── server.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── tools/
│       ├── __init__.py
│       └── datetime_service_tools.py
│
└── mcp-{你的服务名}/           ← 新建目录
    ├── server.py               ← 入口
    ├── Dockerfile              ← 容器构建
    ├── requirements.txt        ← Python 依赖
    ├── platform_integration.py ← 平台注册种子数据
    └── tools/
        ├── __init__.py
        └── {service}_tools.py  ← 工具实现
```

---

## 二、新增一个 MCP Server 的完整步骤

### 第 1 步：创建目录结构

```powershell
cd e:\Python_Project\work_plication\my-mcp-server
mkdir mcp-earthquake\tools
echo $null > mcp-earthquake\tools\__init__.py
```

最终结构：
```
mcp-earthquake/
├── tools/
│   └── __init__.py              # 空文件（Python 包标识）
└── （后续步骤创建的文件）
```

---

### 第 2 步：编写工具实现 `tools/earthquake_tools.py`

核心模式：**在文件底部写一个 `register_xxx_tools(mcp)` 函数**，用 `@mcp.tool()` 装饰器暴露工具。

```python
"""
地震预警工具 — 封装第三方地震预警 API
"""
import os
import httpx
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 配置（从环境变量读取，支持内网切换）
# ============================================================
EARTHQUAKE_API_BASE_URL = os.getenv(
    "EARTHQUAKE_API_BASE_URL",
    "https://api.example.com/earthquake/v1"  # 默认外网地址，内网改 .env
)
EARTHQUAKE_API_KEY = os.getenv("EARTHQUAKE_API_KEY", "")


# ============================================================
# 内部实现函数
# ============================================================

async def _get_latest_earthquakes(limit: int = 10) -> dict:
    """获取最近地震列表。"""
    if not EARTHQUAKE_API_KEY:
        return {"success": False, "error": "EARTHQUAKE_API_KEY 未配置"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{EARTHQUAKE_API_BASE_URL}/latest",
            params={"limit": limit},
            headers={"Authorization": f"Bearer {EARTHQUAKE_API_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "success": True,
        "count": len(data.get("items", [])),
        "earthquakes": [
            {
                "magnitude": eq["magnitude"],
                "location": eq["location"],
                "depth_km": eq["depth"],
                "time": eq["origin_time"],
            }
            for eq in data.get("items", [])
        ],
    }


async def _get_earthquake_alert(region: str = "全国") -> dict:
    """获取指定区域的地震预警信息。"""
    if not EARTHQUAKE_API_KEY:
        return {"success": False, "error": "EARTHQUAKE_API_KEY 未配置"}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{EARTHQUAKE_API_BASE_URL}/alert",
            params={"region": region},
            headers={"Authorization": f"Bearer {EARTHQUAKE_API_KEY}"},
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "success": True,
        "region": region,
        "has_alert": data.get("has_alert", False),
        "level": data.get("alert_level", "无"),
        "message": data.get("message", "当前无地震预警"),
        "issued_at": data.get("issued_at", ""),
    }


# ============================================================
# 工具注册函数（唯一需要暴露给 server.py 的入口）
# ============================================================

def register_earthquake_tools(mcp):
    """将地震预警工具注册到 MCP Server 实例。"""

    @mcp.tool()
    async def earthquake_get_latest(limit: int = 10) -> str:
        """获取最近发生的地震列表。

        Args:
            limit: 返回数量，默认 10
        """
        import json
        result = await _get_latest_earthquakes(limit)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def earthquake_get_alert(region: str = "全国") -> str:
        """获取指定区域的地震预警信息。

        Args:
            region: 区域名称，如 "四川"、"云南"、"全国"
        """
        import json
        result = await _get_earthquake_alert(region)
        return json.dumps(result, ensure_ascii=False, indent=2)
```

**关键约定**：
- 内部函数以 `_` 开头，返回 `dict`
- MCP 工具通过 `@mcp.tool()` 包装，返回 `str`（JSON 字符串）
- 所有外部依赖（API 地址、Key）从环境变量读取，便于内网切换
- 工具名遵循 `{服务前缀}_{动作}` 格式

---

### 第 3 步：创建入口文件 `server.py`

```python
"""
mcp-earthquake — 地震预警 MCP Server

封装第三方地震预警 API，提供地震查询和预警工具。
"""
import os
import sys
import logging
from mcp.server.fastmcp import FastMCP
from tools.earthquake_tools import register_earthquake_tools

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)

# ── 配置 ──
PORT = int(os.getenv("MCP_PORT", "8015"))  # 端口号需全局唯一

# ── 创建 MCP Server ──
mcp = FastMCP(
    name="mcp-earthquake",
    host="0.0.0.0",
    port=PORT,
    json_response=True,
    instructions="地震预警服务 — 提供最近地震列表查询和区域地震预警信息。API Key 在 .env 中配置。",
)

# ── 注册工具 ──
register_earthquake_tools(mcp)

# ── 启动 ──
logger.info(f"mcp-earthquake 启动，端口: {PORT}")

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

---

### 第 4 步：创建 `requirements.txt`

```
mcp>=1.22.0,<2
httpx>=0.27.0
uvicorn>=0.30.0
```

> 如果 API 返回 XML，加 `lxml`；如果需要解析 HTML，加 `beautifulsoup4`。按需添加。
>
> **离线环境准备**：在外网环境预先下载依赖包：
> ```powershell
> mkdir mcp-earthquake\offline_wheels
> pip download -r mcp-earthquake\requirements.txt -d mcp-earthquake\offline_wheels
> ```
> 然后将 `offline_wheels/` 目录和基础镜像 `python:3.11-slim` 一起拷贝到内网。

---

### 第 5 步：创建 `Dockerfile`

**外网版**（可联网构建，带清华镜像加速）：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 清华镜像加速（仅外网构建时需要）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8015

CMD ["python", "server.py"]
```

**离线版**（无网络，用预下载的 wheel 包安装）：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 拷贝预下载的 wheel 包
COPY offline_wheels/ /tmp/wheels/

COPY requirements.txt .
# 从本地 wheel 安装，不访问网络
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels -r requirements.txt

# 清理 wheel 包减小镜像体积
RUN rm -rf /tmp/wheels

COPY . .

EXPOSE 8015

CMD ["python", "server.py"]
```

> **说明**：离线 Dockerfile 多一行 `COPY offline_wheels/`，安装时用 `--no-index --find-links` 指向本地目录。
>
> **端口号**必须与 `server.py` 中的 `MCP_PORT` 和 `docker-compose.yml` 中的端口一致。

---

### 第 6 步：在 `docker-compose.yml` 中注册服务

在 `docker-compose.yml` 文件末尾（`networks:` 之前）添加：

```yaml
  # ============================================================
  # Server N: 地震预警服务
  # ============================================================
  mcp-earthquake:
    build: ./mcp-earthquake
    container_name: mcp-earthquake
    restart: unless-stopped
    ports:
      - "8015:8015"
    environment:
      - TZ=Asia/Shanghai
      - EARTHQUAKE_API_BASE_URL=${EARTHQUAKE_API_BASE_URL:-https://api.example.com/earthquake/v1}
      - EARTHQUAKE_API_KEY=${EARTHQUAKE_API_KEY:-}
    networks:
      - mcp-network
```

**关键说明**：
- `${EARTHQUAKE_API_KEY:-}` — 从根目录 `.env` 读取，未设置时默认为空
- `TZ=Asia/Shanghai` — 所有服务统一时区

---

### 第 7 步：在根目录 `.env` 中添加配置

```bash
# ============================================================
# 地震预警 API 配置
# ============================================================
EARTHQUAKE_API_BASE_URL=https://api.example.com/earthquake/v1
EARTHQUAKE_API_KEY=your-api-key-here
```

> **内网切换**：只需修改 `.env` 中的 `EARTHQUAKE_API_BASE_URL` 指向内网服务地址，不需要改任何代码。

---

### 第 8 步：创建 `platform_integration.py`（平台种子数据）

```python
# ============================================================
# 地震预警 MCP Server — 平台集成指南
# ============================================================
# 将以下内容添加到 Agent Web 平台的 seed.py 中进行注册
# ============================================================

EARTHQUAKE_MCP_SEED = {
    "id": "mcp-earthquake-001",
    "name": "地震预警 MCP",
    "category": "生活服务",
    "tags": ["地震", "预警", "自然灾害"],
    "authorId": "system",
    "authorName": "MCP官方",
    "stars": 0,
    "installs": 0,
    "status": "active",
    "createdAt": "now",
    "updatedAt": "now",
    "version": "1.0.0",
    "license": "MIT",
    "contactPhone": "",
    "logoUrl": "_random_local_logo()",
    "overview": "地震预警查询服务。支持查询最近地震列表、获取区域地震预警信息。数据来源于第三方地震预警API。",
    "usageInstructions": "1. 确保 EARTHQUAKE_API_KEY 已配置\n2. 平台对话中勾选此 MCP 即可使用",
    "endpoint": "http://127.0.0.1:8015",
    "serverConfig": {
        "mcpServers": {
            "mcp-earthquake": {
                "command": "python",
                "args": ["server.py", "--port", "8015", "--transport", "sse"],
                "cwd": "./individual-mcp/mcp-earthquake"
            }
        }
    },
    "tools": [
        {"name": "earthquake_get_latest", "description": "获取最近发生的地震列表"},
        {"name": "earthquake_get_alert", "description": "获取指定区域的地震预警信息"},
    ],
}
```

---

### 第 9 步：构建 & 启动

#### 外网环境

```powershell
cd e:\Python_Project\work_plication\my-mcp-server

# 仅构建新服务
docker-compose build --no-cache mcp-earthquake

# 启动新服务
docker-compose up -d mcp-earthquake

# 查看日志确认正常
docker-compose logs -f mcp-earthquake
```

#### 离线内网环境

前提：已将基础镜像 `python:3.11-slim` 导入内网 Docker、已准备好 `offline_wheels/` 目录。

```powershell
cd e:\Python_Project\work_plication\my-mcp-server

# 确认基础镜像已加载
docker images python:3.11-slim

# 使用离线版 Dockerfile 构建（需临时替换或直接指定）
# 方案一：将离线版 Dockerfile 内容覆盖 Dockerfile 后构建
docker build --no-cache -t mcp-earthquake:latest -f mcp-earthquake\Dockerfile mcp-earthquake

# 方案二（推荐）：直接通过 docker-compose 构建（Dockerfile 已经是离线版）
docker-compose build --no-cache mcp-earthquake

# 启动
docker-compose up -d mcp-earthquake
```

正常启动应看到：
```
mcp-earthquake  | mcp-earthquake 启动，端口: 8015
```

---

### 第 10 步：内网迁移（二选一）

#### 方案 A：外网构建镜像 → 导出 → 内网加载（推荐，最省事）

适用于：所有依赖包 + 基础镜像在外网一次性搞定，内网纯搬运。

```powershell
# === 外网环境 ===

# 1. 构建镜像
docker-compose build --no-cache mcp-earthquake

# 2. 导出新镜像
docker save -o mcp-earthquake.tar mcp-earthquake:latest

# 3. 将以下文件拷贝到内网机器：
#    - mcp-earthquake.tar
#    - docker-compose.yml（已新增 mcp-earthquake 服务定义）
#    - .env（已新增 API Key 配置）

# === 内网环境 ===

# 4. 加载镜像
docker load -i mcp-earthquake.tar

# 5. 修改 .env 指向内网 API 地址（如有）
# EARTHQUAKE_API_BASE_URL=http://192.168.1.100:8080/earthquake/v1

# 6. 启动
docker-compose up -d
```

> 这是本项目的标准做法。优点：内网不需要编译工具、pip、网络，纯 `docker load` + `docker-compose up -d` 两步即可。

#### 方案 B：内网离线构建（pip wheel 本地安装）

适用于：基础镜像已在内网、有预下载的 wheel 包、需要在本地从源码构建。

```powershell
# === 外网环境 ===

# 1. 下载基础镜像并导出
docker pull python:3.11-slim
docker save -o python-3.11-slim.tar python:3.11-slim

# 2. 下载所有依赖包的 wheel 文件
mkdir mcp-earthquake\offline_wheels
pip download -r mcp-earthquake\requirements.txt -d mcp-earthquake\offline_wheels

# 3. 使用离线版 Dockerfile（见第 5 步）
#    Dockerfile 中 COPY offline_wheels/ + pip install --no-index --find-links

# 4. 拷贝到内网：
#    - python-3.11-slim.tar
#    - mcp-earthquake/（含 offline_wheels/ + 离线版 Dockerfile）

# === 内网环境 ===

# 5. 加载基础镜像
docker load -i python-3.11-slim.tar

# 6. 从本地构建（Dockerfile 中 --no-index --find-links 指向 offline_wheels/）
cd my-mcp-server
docker-compose build --no-cache mcp-earthquake

# 7. 启动
docker-compose up -d mcp-earthquake
```

---

## 三、端口分配表（避免冲突）

| 服务 | 端口 |
|---|---|
| mcp-file-doc | 8000 |
| mcp-markitdown | 8001 |
| mcp-browser-playwright | 8002 |
| mcp-data-platform | 8003 |
| mcp-sequential-thinking | 8004 |
| mcp-spreadsheet-pdf | 8005 |
| mcp-ops-monitor | 8007 |
| mcp-datetime | 8010 |
| ppt-master-mcp | 8011 |
| mcp-fetch-intranet | 8012 |
| mcp-drawio | 8013 |
| **mcp-earthquake** | **8015** |
| （新服务） | 80xx（自选未占用端口） |

---

## 四、关键约定速查

| 约定 | 说明 |
|---|---|
| 目录名 | `mcp-{服务名}` |
| 工具文件 | `tools/{服务名}_tools.py` |
| 注册函数 | `register_{服务名}_tools(mcp)` |
| 工具命名 | `{服务前缀}_{动作}`，如 `earthquake_get_latest` |
| 返回格式 | 内部函数返回 `dict`，MCP 工具 `json.dumps()` 为 `str` |
| API 配置 | 从 `os.getenv("XXX_API_KEY")` 读取，不走硬编码 |
| 端口 | 全局唯一，在端口分配表中登记 |
| 容器时区 | `TZ=Asia/Shanghai` |
| 共享网络 | `networks: - mcp-network` |

---

## 五、完整文件清单（新增一个 MCP Server 需创建的文件）

```
mcp-{服务名}/
├── server.py               ← 入口（FastMCP 初始化 + register_tools）
├── Dockerfile              ← 容器构建（外网版 / 离线版二选一）
├── requirements.txt        ← Python 依赖
├── platform_integration.py ← 平台种子数据（MCP）
├── offline_wheels/         ← 可选：离线构建时存放预下载的 .whl 包
└── tools/
    ├── __init__.py         ← 空文件（Python 包标识）
    └── {服务名}_tools.py   ← 工具实现 + register_xxx_tools()
```

**需要编辑的已有文件**：
- `docker-compose.yml` — 新增服务定义
- `.env` — 新增 API Key / 地址配置
- `README.md` — 更新服务总览表
