"""
mcp-spreadsheet-pdf - Excel / CSV / PDF 操作 MCP Server

负责 Excel CRUD、CSV 结构化读写、PDF 提取/创建/合并/拆分。
"""
from mcp.server.fastmcp import FastMCP
from tools.excel_tools import register_excel_tools
from tools.csv_tools import register_csv_tools
from tools.pdf_tools import register_pdf_tools
import sys, os

# 创建服务器
mcp = FastMCP("mcp-spreadsheet-pdf", host="0.0.0.0", port=8012, json_response=True)

# 沙箱根目录
if sys.platform == "win32":
    base_dir = os.path.join(os.path.expanduser("~"), "mcp-data")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Windows] 沙箱根目录: {base_dir}", file=sys.stderr)
else:
    base_dir = "/data"
    print(f"[Linux] 沙箱根目录: {base_dir}", file=sys.stderr)

os.makedirs(os.path.join(base_dir, "uploads"), exist_ok=True)

# 注册工具
register_excel_tools(mcp, base_dir=base_dir)
register_csv_tools(mcp, base_dir=base_dir)
register_pdf_tools(mcp, base_dir=base_dir)

print(f"[MCP Server] mcp-spreadsheet-pdf 已就绪，端口: 8012", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
