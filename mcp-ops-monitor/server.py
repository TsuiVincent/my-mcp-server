from mcp.server.fastmcp import FastMCP
from tools.system_monitor_tools import register_monitor_tools
from tools.log_analyzer_tools import register_log_analyzer_tools
from tools.custom_tools import register_custom_tools
import sys, logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

# 创建服务器
mcp = FastMCP("mcp-ops-monitor", host="0.0.0.0", port=19106)

# 注册所有工具模块
register_monitor_tools(mcp)
register_log_analyzer_tools(mcp)
register_custom_tools(mcp)

print(f"[MCP Server] mcp-ops-monitor 已就绪，端口: 19106", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
