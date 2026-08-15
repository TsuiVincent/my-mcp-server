"""
mcp-mineru-bridge - MinerU 文档解析 MCP 桥接服务器

作为轻量级桥接层，将远程 MinerU 服务 (FastAPI REST API) 包装为 MCP 工具。
无需本地 GPU 和模型文件，通过 HTTP 调用已有 MinerU 部署。
"""
import os
import sys
from mcp.server.fastmcp import FastMCP
from tools.parse_tools import register_parse_tools
from tools.health_tools import register_health_tools

# 从环境变量读取配置
MINERU_API_URL = os.environ.get("MINERU_API_URL", "http://localhost:8000")
MINERU_API_KEY = os.environ.get("MINERU_API_KEY", "")

# 创建服务器
mcp = FastMCP("mcp-mineru-bridge", host="0.0.0.0", port=19112, json_response=True)

# 注册工具
register_parse_tools(mcp, mineru_api_url=MINERU_API_URL, mineru_api_key=MINERU_API_KEY)
register_health_tools(mcp, mineru_api_url=MINERU_API_URL, mineru_api_key=MINERU_API_KEY)

print(f"[MCP Server] mcp-mineru-bridge 已就绪，端口: 19112", file=sys.stderr)
print(f"[MinerU] 后端 API: {MINERU_API_URL}", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")