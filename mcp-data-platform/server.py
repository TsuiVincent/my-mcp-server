from mcp.server.fastmcp import FastMCP
from tools.user_kb_sqlite_tools import register_user_kb_tools
from tools.database_tools import register_database_tools
from tools.python_executor_tools import register_python_executor_tools
from tools.visualization_tools import register_visualization_tools
from tools.knowledge_search_tools import register_knowledge_search_tools
import sys, os, logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

# 创建服务器
mcp = FastMCP("mcp-data-platform", host="0.0.0.0", port=19104)

# 用户数据根目录
if sys.platform == "win32":
    base_dir = os.path.join(os.path.expanduser("~"), "mcp-user-data")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Windows] 数据根目录: {base_dir}", file=sys.stderr)
else:
    base_dir = "/data/mcp-user-data"
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Linux] 数据根目录: {base_dir}", file=sys.stderr)

# 注册所有工具模块
register_user_kb_tools(mcp, base_dir=base_dir)
register_database_tools(mcp, base_dir=base_dir)
register_python_executor_tools(mcp, base_dir=base_dir)
register_visualization_tools(mcp, base_dir=base_dir)
register_knowledge_search_tools(mcp)

print(f"[MCP Server] mcp-data-platform 已就绪，端口: 19104", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
