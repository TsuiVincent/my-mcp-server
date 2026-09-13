from mcp.server.fastmcp import FastMCP
from tools.api_tools import register_api_tools
from tools.web_scraper_tools import register_web_scraper_tools
from tools.spider_tools import register_spider_tools
from tools.config_manager_tools import register_config_manager_tools
import sys, os, logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)

# 创建服务器
mcp = FastMCP("mcp-fetch-intranet", host="0.0.0.0", port=19107)

# 数据根目录（配置管理SQLite持久化用）
if sys.platform == "win32":
    base_dir = os.path.join(os.path.expanduser("~"), "mcp-user-data")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Windows] 数据根目录: {base_dir}", file=sys.stderr)
else:
    base_dir = "/data/mcp-user-data"
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Linux] 数据根目录: {base_dir}", file=sys.stderr)

# 注册所有工具模块
register_api_tools(mcp)
register_web_scraper_tools(mcp)
register_spider_tools(mcp, base_dir=base_dir)
register_config_manager_tools(mcp, base_dir=base_dir)

_render_status = "开启(Chromium)" if os.environ.get("WITH_RENDER", "0") == "1" else "关闭(仅静态抓取)"
print(f"[MCP Server] mcp-fetch-intranet 已就绪，端口: 19107，JS渲染: {_render_status}", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
