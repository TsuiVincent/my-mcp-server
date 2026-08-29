"""
mcp-office-word - Word 通用操作 MCP Server

从 mcp-file-doc 拆分而来，只暴露通用 Word 文档读写创作能力：
  - word_tools：word_read / word_create_doc / word_add_paragraph / word_add_heading / word_add_table
  - file_tools：通用文件 9 个（file_read/write/edit、dir_list/create、read_json、file_upload/download/list_uploads）
"""
from mcp.server.fastmcp import FastMCP
from starlette.responses import FileResponse
from tools.file_tools import register_file_tools
from tools.word_tools import register_word_tools
import sys, os

# 创建服务器
mcp = FastMCP("mcp-office-word", host="0.0.0.0", port=19121, json_response=True)

# 沙箱根目录（可用环境变量 MCP_DATA_DIR 覆盖）
if sys.platform == "win32":
    base_dir = os.environ.get("MCP_DATA_DIR") or os.path.join(os.path.expanduser("~"), "mcp-data")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[Windows] 沙箱根目录: {base_dir}", file=sys.stderr)
else:
    base_dir = os.environ.get("MCP_DATA_DIR") or "/data"
    print(f"[Linux] 沙箱根目录: {base_dir}", file=sys.stderr)

os.makedirs(os.path.join(base_dir, "uploads"), exist_ok=True)

# 服务器对外基础 URL（用于生成文件下载链接）
server_base_url = os.environ.get("MCP_SERVER_BASE_URL", "")


@mcp.custom_route("/download/{filepath:path}", methods=["GET"])
async def download_file(request):
    """安全文件下载路由，只允许访问 base_dir 目录下的文件"""
    from starlette.responses import JSONResponse
    filepath = request.path_params["filepath"]
    target_path = os.path.abspath(os.path.join(base_dir, filepath))
    if not target_path.startswith(os.path.abspath(base_dir)):
        return JSONResponse({"error": "路径越权"}, status_code=403)
    if not os.path.isfile(target_path):
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    filename = os.path.basename(target_path)
    return FileResponse(target_path, filename=filename)


# 注册工具
register_file_tools(mcp, base_dir=base_dir)
register_word_tools(mcp, base_dir=base_dir, server_base_url=server_base_url)

print(f"[MCP Server] mcp-office-word 已就绪，端口: 19121，下载基地址: {server_base_url}", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
