"""
mcp-markitdown - 文档格式转换 MCP Server

负责 Markdown 解析渲染、文件格式转换（PDF/Word/Excel/HTML 等 → Markdown）功能。
独立承载文档转换工具。
"""
from mcp.server.fastmcp import FastMCP
from tools.markitdown_tools import register_markitdown_tools
import sys, logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

# 创建服务器
mcp = FastMCP("mcp-markitdown", host="0.0.0.0", port=19101, json_response=True)

# 注册工具
register_markitdown_tools(mcp)

print("[MCP Server] mcp-markitdown 已就绪，端口: 19101", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
