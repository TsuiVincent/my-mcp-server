"""
mcp-spreadsheet-pdf 文件传输工具模块

提供 Base64 文件上传/下载能力，与 mcp-file-doc 的 file_upload/file_download 对齐，
使平台可先上传 Excel 文件到本服务器，再调用 smart_fill_excel / fill_excel_form 等本地路径工具。

工具列表:
- file_upload         Base64 上传文件到服务器 uploads/ 目录
- file_download       从服务器下载文件（Base64 返回）
- file_list_uploads   列出已上传文件
"""

import os
import sys
import json
import base64
import asyncio
from datetime import datetime
from mcp.server.fastmcp import FastMCP


def register_file_tools(mcp: FastMCP, base_dir: str = "/data", **kwargs):
    """注册文件传输工具"""
    upload_dir = os.path.join(base_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    server_base_url = kwargs.get("server_base_url", "")

    def _safe_abs_path(path: str) -> str:
        """安全路径：绝对路径必须落在 base_dir 沙箱内，相对路径追加 base_dir"""
        if os.path.isabs(path):
            if not path.startswith(os.path.abspath(base_dir)):
                raise ValueError(f"路径越权: {path}")
            return path
        return os.path.join(base_dir, path)

    def _make_download_url(abs_file_path: str) -> str:
        url_base = server_base_url
        if not url_base:
            try:
                ctx = mcp.get_context()
                req = ctx.request_context.request
                if req is not None:
                    host = req.headers.get("x-forwarded-host") or req.headers.get("host", "localhost:19109")
                    proto = req.headers.get("x-forwarded-proto", "http")
                    url_base = f"{proto}://{host}"
            except Exception:
                url_base = "http://localhost:19109"
        if not url_base:
            return ""
        try:
            abs_base = os.path.abspath(base_dir)
            abs_file = os.path.abspath(abs_file_path)
            if abs_file.startswith(abs_base):
                rel = os.path.relpath(abs_file, abs_base).replace("\\", "/")
                return f"{url_base}/download/{rel}"
        except Exception:
            pass
        return ""

    @mcp.tool()
    async def file_upload(content_base64: str, filename: str) -> str:
        """将客户端文件上传到服务器（Base64）。

Args:
    content_base64: 文件的 Base64 编码字符串
    filename: 保存的文件名（如 "报名表.xlsx"），自动存入 uploads/ 目录

Returns:
    JSON，包含 server_path（后续调用 smart_fill_excel / fill_excel_form 等工具时使用）
"""
        try:
            raw = base64.b64decode(content_base64)
            safe_name = os.path.basename(filename)
            target = os.path.join(upload_dir, safe_name)
            loop = asyncio.get_event_loop()

            def _write():
                with open(target, 'wb') as f:
                    f.write(raw)
            await loop.run_in_executor(None, _write)
            return json.dumps({
                "status": "ok",
                "server_path": target,
                "file_size": len(raw),
                "filename": safe_name,
            }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def file_download(path: str) -> str:
        """从服务器下载文件（Base64 编码返回）。

Args:
    path: 服务器上的文件路径（支持 file_upload 返回的 server_path 或服务器本地路径）

Returns:
    JSON，包含 base64_content、filename、file_size、mime_type。
"""
        try:
            target = _safe_abs_path(path)
            if not os.path.isfile(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            filename = os.path.basename(target)
            ext = os.path.splitext(filename)[1].lower()
            mime_map = {
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.xls': 'application/vnd.ms-excel',
                '.csv': 'text/csv',
                '.pdf': 'application/pdf',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.txt': 'text/plain',
                '.json': 'application/json',
            }
            mime = mime_map.get(ext, 'application/octet-stream')
            loop = asyncio.get_event_loop()

            def _read():
                with open(target, 'rb') as f:
                    return base64.b64encode(f.read()).decode('ascii')
            content = await loop.run_in_executor(None, _read)
            return json.dumps({
                "status": "ok",
                "filename": filename,
                "file_size": os.path.getsize(target),
                "mime_type": mime,
                "base64_content": content,
                "usage_note": "将 base64_content 解码后写入文件即可得到原始文件。",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def file_list_uploads() -> str:
        """列出所有已上传到服务器的文件"""
        try:
            items = os.listdir(upload_dir)
            result = []
            for name in items:
                full = os.path.join(upload_dir, name)
                if os.path.isfile(full):
                    result.append({
                        "name": name,
                        "size": os.path.getsize(full),
                        "server_path": full,
                        "mtime": datetime.fromtimestamp(os.path.getmtime(full)).isoformat()
                    })
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    print("[mcp-spreadsheet-pdf] 文件传输工具已注册", flush=True)
