"""
mcp-office-excel - Excel / CSV 通用操作 MCP Server

从 mcp-spreadsheet-pdf 拆分而来，只暴露通用 Excel CRUD 与 CSV 读写分析：
  - excel_tools：excel_create/read/get_sheets/write_cell/write_row/write_data/insert_rows/delete_rows/merge_cells/set_column_width/set_cell_style/add_sheet（12）
  - csv_tools：csv_read / csv_write / csv_analyze（3）
智能填表（parse/fill/smart_fill_excel）已拆分到 mcp-form-fill。
"""
from mcp.server.fastmcp import FastMCP
from tools.excel_tools import register_excel_tools
from tools.csv_tools import register_csv_tools
import sys, os

# 创建服务器
mcp = FastMCP("mcp-office-excel", host="0.0.0.0", port=19122, json_response=True)

# 沙箱根目录（可用环境变量 MCP_DATA_DIR 覆盖）
if sys.platform == "win32":
    base_dir = os.environ.get("MCP_DATA_DIR") or os.path.join(os.path.expanduser("~"), "mcp-data")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Windows] 沙箱根目录: {base_dir}", file=sys.stderr)
else:
    base_dir = os.environ.get("MCP_DATA_DIR") or "/data"
    print(f"[Linux] 沙箱根目录: {base_dir}", file=sys.stderr)

os.makedirs(os.path.join(base_dir, "uploads"), exist_ok=True)


@mcp.custom_route("/download/{filepath:path}", methods=["GET"])
async def download_file(request):
    """安全文件下载路由，只允许访问 base_dir 目录下的文件"""
    from starlette.responses import FileResponse, JSONResponse
    filepath = request.path_params["filepath"]
    target_path = os.path.abspath(os.path.join(base_dir, filepath))
    if not target_path.startswith(os.path.abspath(base_dir)):
        return JSONResponse({"error": "路径越权"}, status_code=403)
    if not os.path.isfile(target_path):
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    filename = os.path.basename(target_path)
    return FileResponse(target_path, filename=filename)


# 注册工具
register_excel_tools(mcp, base_dir=base_dir)
register_csv_tools(mcp, base_dir=base_dir)

print(f"[MCP Server] mcp-office-excel 已就绪，端口: 19122", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
