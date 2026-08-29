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
import re
import json
import base64
import asyncio
from datetime import datetime
from mcp.server.fastmcp import FastMCP


# Docker 容器内宿主目录挂载映射（环境变量配置）
# 格式: HOST_DOWNLOADS=/mnt/host/downloads  HOST_DESKTOP=/mnt/host/desktop
_HOST_MOUNTS = {
    "Downloads": os.environ.get("HOST_DOWNLOADS", ""),
    "Desktop": os.environ.get("HOST_DESKTOP", ""),
    "Documents": os.environ.get("HOST_DOCUMENTS", ""),
}


def _map_windows_to_linux(path: str, base_dir: str) -> str:
    """将 Windows 绝对路径映射到容器内挂载点 (C:\\Users\\xxx\\Downloads\\file.docx -> /mnt/host/downloads/file.docx)"""
    if sys.platform == "win32" or not path:
        return ""

    # 匹配 Windows 绝对路径: C:\Users\xxx\... 或 D:\...
    m = re.match(r'^[A-Za-z]:\\([Uu]sers\\)?([^\\]+)\\(.+)$', path)
    if not m:
        # 尝试更简单的盘符路径: C:\path -> /mnt/host/... (Docker Desktop Windows 自动挂载方式)
        m2 = re.match(r'^[A-Za-z]:\\(.+)$', path)
        if m2 and os.path.exists(f"/mnt/host"):
            candidate = os.path.join("/mnt/host", m2.group(1).replace("\\", "/"))
            if os.path.exists(candidate):
                return candidate
        return ""

    username = m.group(2)  # lx
    relative = m.group(3)  # Downloads\file.docx

    # 尝试匹配已知目录
    for folder, mount_point in _HOST_MOUNTS.items():
        if not mount_point:
            continue
        folder_lower = folder.lower()
        if relative.lower().startswith(folder_lower):
            rest = relative[len(folder):].lstrip("\\").replace("\\", "/")
            candidate = os.path.join(mount_point, rest)
            if os.path.exists(candidate):
                return candidate

    # 通用回退：尝试 /mnt/host/ 前缀
    if _HOST_MOUNTS.get("Downloads"):
        filename = os.path.basename(path.replace("\\", "/"))
        for mp in _HOST_MOUNTS.values():
            if not mp:
                continue
            candidate = os.path.join(mp, filename)
            if os.path.exists(candidate):
                return candidate

    return ""


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
                    host = req.headers.get("x-forwarded-host") or req.headers.get("host", "localhost:19120")
                    proto = req.headers.get("x-forwarded-proto", "http")
                    url_base = f"{proto}://{host}"
            except Exception:
                url_base = "http://localhost:19120"
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
