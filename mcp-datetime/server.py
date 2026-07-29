"""
mcp-datetime - 时间日期服务 MCP Server

从 mcp-fetch-intranet 拆分而来，独立承载时间日期处理工具（7个）。
"""
from mcp.server.fastmcp import FastMCP
from tools.datetime_service_tools import register_datetime_tools
import sys, logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

mcp = FastMCP("mcp-datetime", host="0.0.0.0", port=8010, json_response=True)

register_datetime_tools(mcp)

print("[MCP Server] mcp-datetime 已就绪，端口: 8010", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
