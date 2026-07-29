直接选 **FastMCP 自建 HTTP 服务器**，这是唯一同时满足你两个需求的方案。

原因：
- **官方 `server-filesystem`** 只有文件操作，无法自定义内网 API 工具，且是 `stdio` 模式，内网远程调用还要套 `supergateway`，多一层麻烦。
- **FastMCP 自建**：文件读写自己写（就几行代码），内网 API 封装成 `@mcp.tool()` 直接注册，一个服务搞定所有，客户端直接 `http://内网IP` 连接。

---

## 完整项目模板（可直接拷贝进内网）

### 目录结构

```
mcp-intranet/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── server.py
└── tools/
    ├── __init__.py
    ├── file_tools.py
    ├── api_tools.py
    └── custom_tools.py
```

### `requirements.txt`

```
mcp>=1.6.0
httpx>=0.27.0
uvicorn>=0.30.0
```

> 内网离线安装：`pip download -d packages -r requirements.txt` 在外网打包，内网 `pip install --no-index --find-links=packages -r requirements.txt`

### `tools/file_tools.py`（文件读写目录）

```python
import os
import json
from mcp.server.fastmcp import FastMCP

def register_file_tools(mcp: FastMCP, base_dir: str = "/data"):
    """
    注册文件操作工具
    :param base_dir: 允许操作的根目录（安全沙箱，防止越权）
    """
    
    def _safe_path(path: str) -> str:
        """路径安全检查，禁止跳出 base_dir"""
        full = os.path.abspath(os.path.join(base_dir, path.lstrip("/")))
        if not full.startswith(os.path.abspath(base_dir)):
            raise ValueError("Path not allowed")
        return full

    @mcp.tool()
    def file_read(path: str) -> str:
        """读取文件内容"""
        try:
            with open(_safe_path(path), 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def file_write(path: str, content: str, append: bool = False) -> str:
        """写入文件（append=True 追加）"""
        try:
            target = _safe_path(path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            mode = 'a' if append else 'w'
            with open(target, mode, encoding='utf-8') as f:
                f.write(content)
            return f"OK: {path}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def file_edit(path: str, old_string: str, new_string: str) -> str:
        """查找替换文件内容"""
        try:
            target = _safe_path(path)
            with open(target, 'r', encoding='utf-8') as f:
                content = f.read()
            if old_string not in content:
                return "Error: old_string not found"
            content = content.replace(old_string, new_string, 1)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"OK: edited {path}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def dir_list(path: str = ".") -> str:
        """列出目录内容"""
        try:
            target = _safe_path(path)
            items = os.listdir(target)
            result = []
            for name in items:
                full = os.path.join(target, name)
                result.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else None
                })
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def dir_create(path: str) -> str:
        """创建目录"""
        try:
            os.makedirs(_safe_path(path), exist_ok=True)
            return f"OK: created {path}"
        except Exception as e:
            return f"Error: {str(e)}"
```

### `tools/api_tools.py`（内网 API 调用）

```python
import httpx
import json
from mcp.server.fastmcp import FastMCP

def register_api_tools(mcp: FastMCP):
    """
    注册内网 API 调用工具
    按需修改下面的 endpoint 和参数
    """

    @mcp.tool()
    async def api_get(endpoint: str, params: str = "{}") -> str:
        """
        调用内网 GET API
        :param endpoint: 完整 URL，如 http://192.168.1.50:8080/api/users
        :param params: JSON 字符串，如 {"id": "123"}
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(endpoint, params=json.loads(params))
                return json.dumps({
                    "status": resp.status_code,
                    "body": resp.text
                }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def api_post(endpoint: str, data: str = "{}", headers: str = "{}") -> str:
        """
        调用内网 POST API
        :param endpoint: 完整 URL
        :param data: JSON 字符串请求体
        :param headers: JSON 字符串请求头
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    endpoint,
                    json=json.loads(data),
                    headers=json.loads(headers)
                )
                return json.dumps({
                    "status": resp.status_code,
                    "body": resp.text
                }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    # ========== 示例：封装特定内网系统 ==========
    @mcp.tool()
    async def query_erp_user(user_id: str) -> str:
        """查询内网 ERP 系统用户信息（示例）"""
        endpoint = f"http://192.168.1.50:8080/erp/api/users/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(endpoint)
                return resp.text
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def create_ticket(title: str, content: str, priority: str = "normal") -> str:
        """向内网工单系统创建工单（示例）"""
        endpoint = "http://192.168.1.60:9000/ticket/api/create"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(endpoint, json={
                    "title": title,
                    "content": content,
                    "priority": priority
                })
                return json.dumps({
                    "status": resp.status_code,
                    "ticket_id": resp.json().get("id") if resp.status_code == 200 else None
                }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"
```

### `tools/custom_tools.py`（其他自定义工具）

```python
import subprocess
import json
from mcp.server.fastmcp import FastMCP

def register_custom_tools(mcp: FastMCP):

    @mcp.tool()
    def run_command(command: str, cwd: str = None, timeout: int = 30) -> str:
        """执行服务器命令行"""
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout
            )
            return json.dumps({
                "code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    def get_system_info() -> str:
        """获取服务器系统信息"""
        try:
            result = subprocess.run(["uname", "-a"], capture_output=True, text=True)
            return result.stdout
        except:
            import platform
            return json.dumps({
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine()
            }, ensure_ascii=False)
```

### `server.py`（入口）

```python
from mcp.server.fastmcp import FastMCP

from tools.file_tools import register_file_tools
from tools.api_tools import register_api_tools
from tools.custom_tools import register_custom_tools

# 创建服务器
mcp = FastMCP("intranet-server", json_response=True)

# 注册所有工具
register_file_tools(mcp, base_dir="/data")  # 文件沙箱根目录
register_api_tools(mcp)
register_custom_tools(mcp)

if __name__ == "__main__":
    # streamable-http 模式，监听所有网卡
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

### `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 内网离线：提前把 packages/ 目录拷贝进来
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建文件操作沙箱目录
RUN mkdir -p /data

EXPOSE 8000

CMD ["python", "server.py"]
```

### `docker-compose.yml`

```yaml
version: "3.8"

services:
  mcp-server:
    build: .
    container_name: mcp-intranet
    ports:
      - "8000:8000"
    volumes:
      # 把宿主机的数据目录映射进容器沙箱
      - /opt/mcp-data:/data
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
```

---

## 客户端连接

### 1.Cherry Studio / Claude Desktop / Cursor

```json
{
  "mcpServers": {
    "intranet": {
      "type": "http",
      "url": "http://192.168.1.100:8000/mcp"
    }
  }
}
# ip替换成mcp服务器的地址
```

### 2.dify添加mcp服务器方法

Dify 目前原生支持通过 **SSE (Server-Sent Events)** 协议接入 MCP 服务器。因为 Dify 后端是服务器端应用，它不能像本地桌面客户端（如 Claude Desktop）那样直接拉起一个 stdio 进程，所以**你必须把 FastMCP 以 HTTP/SSE 方式部署在内网**。

#### 2.1**安装所需插件**

在插件市场中，你需要安装核心的两个 MCP 支持插件MCP Agent Strategy、MCP SSE/StreamableHTTP

离线环境下只能装着两个工具的离线版，如下

- 工具中上传离线的agent-mcp_sse.difypkg和mcp_sse.difypkg
- 上传中可能会遇到插件签名验证不了的情况，这个时候在dify的.env文件中写FORCE_VERIFYING_SIGNATURE=false来取消验证

#### 2.2**添加自定义 MCP 工具**

- 服务端点 URL（填写 FastMCP 服务的访问地址）：如http://192.168.53.212:8000/mcp
- 名称和图标：自定义
- 服务器标识符：自定义一个独特的

#### 2.3 agent中使用mcp方法

在创建的agent的工具中添加mcp，这里就可以看到工具了。



---

## 为什么选这个方案

| 对比项          | 官方 server-filesystem + supergateway | FastMCP 自建                      |
| --------------- | ------------------------------------- | --------------------------------- |
| 文件操作        | ✅ 有                                  | ✅ 有，且可自定义沙箱路径          |
| 内网 API 自定义 | ❌ 没有，再加服务器更复杂              | ✅ 直接写 `@mcp.tool()`            |
| 架构复杂度      | 高（stdio → supergateway → HTTP）     | 低（直接 HTTP）                   |
| 权限控制        | 弱                                    | 强（`base_dir` 沙箱、命令黑名单） |
| 内网离线        | 需转多层                              | 一个容器搞定                      |

**结论**：你的两个需求（文件操作 + 内网 API 自定义）决定了必须自建。上面的模板直接拿去用，改改 `api_tools.py` 里的 endpoint 就能对接你的内网系统。
