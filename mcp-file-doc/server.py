"""
mcp-file-doc - 文件操作与文档智能处理 MCP Server

负责文件 I/O、远程传输、智能填表、Word 高级操作等功能。
Markitdown 格式转换已拆分到 mcp-markitdown (8007)。
"""
from mcp.server.fastmcp import FastMCP
from starlette.responses import FileResponse
from tools.file_tools import register_file_tools
from tools.auto_fill_form_tools import register_auto_fill_tools
from tools.word_tools import register_word_tools
import sys, os

# 创建服务器
mcp = FastMCP("mcp-file-doc", host="0.0.0.0", port=8002, json_response=True)

# 根据平台设置写入沙箱根目录
if sys.platform == "win32":
    base_dir = os.path.join(os.path.expanduser("~"), "mcp-data")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Windows] 沙箱根目录: {base_dir}", file=sys.stderr)
else:
    base_dir = "/data"
    print(f"[Linux] 沙箱根目录: {base_dir}", file=sys.stderr)

# 服务器对外基础 URL（用于生成文件下载链接）
server_base_url = os.environ.get("MCP_SERVER_BASE_URL", "")


@mcp.custom_route("/download/{filepath:path}", methods=["GET"])
async def download_file(request):
    """安全文件下载路由，只允许访问 base_dir 目录下的文件"""
    filepath = request.path_params["filepath"]
    target_path = os.path.abspath(os.path.join(base_dir, filepath))
    if not target_path.startswith(os.path.abspath(base_dir)):
        from starlette.responses import JSONResponse
        return JSONResponse({"error": "路径越权"}, status_code=403)
    if not os.path.isfile(target_path):
        from starlette.responses import JSONResponse
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    filename = os.path.basename(target_path)
    return FileResponse(
        target_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# 注册工具
register_file_tools(mcp, base_dir=base_dir)
register_auto_fill_tools(mcp, base_dir=base_dir, server_base_url=server_base_url)
register_word_tools(mcp, base_dir=base_dir, server_base_url=server_base_url)

print(f"[MCP Server] mcp-file-doc 已就绪，端口: 8002，下载基地址: {server_base_url}", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
