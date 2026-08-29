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
    """
    注册文件操作工具
    :param base_dir: 写入沙箱根目录
    """
    upload_dir = os.path.join(base_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    def _resolve_path(path: str) -> str:
        """统一路径解析：支持 Linux 绝对路径、Windows路径(Docker)、相对路径"""

        # 1. Docker容器内收到Windows路径 -> 映射到挂载点
        mapped = _map_windows_to_linux(path, base_dir)
        if mapped:
            return mapped

        # 2. Linux 绝对路径：已存在则直接使用（仅限 base_dir 沙箱与宿主挂载点内），
        #    否则映射到 base_dir 沙箱，避免越权读取沙箱外文件（如 /etc/passwd）
        if path.startswith('/'):
            abs_base = os.path.abspath(base_dir)
            allowed = [abs_base] + [m for m in _HOST_MOUNTS.values() if m]
            norm = os.path.normpath(path)
            if any(norm == a or norm.startswith(a + os.sep) for a in allowed) and os.path.exists(norm):
                return norm
            return os.path.join(base_dir, path.lstrip('/').replace('/', os.sep))

        # 3. 相对路径（含 ../ 穿越防护，防止拼接到沙箱外）
        if not os.path.isabs(path):
            abs_base = os.path.abspath(base_dir)
            full = os.path.normpath(os.path.join(base_dir, path))
            if full == abs_base or full.startswith(abs_base + os.sep):
                return full
            raise ValueError(f"路径越权: {path}")

        return path

    def _safe_read_path(path: str) -> str:
        full = _resolve_path(path)
        if os.path.exists(full):
            return full
        if not os.path.isabs(path):
            from .auto_fill_form_tools import _search_file
            found = _search_file(path)
            if found:
                return found
        raise ValueError(f"文件不存在: {path}")

    def _safe_write_path(path: str) -> str:
        full = _resolve_path(path)
        home = os.path.expanduser("~")
        allowed_dirs = [
            os.path.abspath(base_dir),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
        ]
        for allowed in allowed_dirs:
            if full.startswith(os.path.abspath(allowed)):
                return full
        raise ValueError(f"写入路径越权: {path}，仅允许: {base_dir}、Downloads、Desktop、Documents")

    # ===========================
    # 基础文件工具
    # ===========================

    @mcp.tool()
    async def file_read(path: str) -> str:
        """读取文件内容"""
        try:
            loop = asyncio.get_event_loop()
            def _read():
                with open(_safe_read_path(path), 'r', encoding='utf-8') as f:
                    return f.read()
            return await loop.run_in_executor(None, _read)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def file_write(path: str, content: str, append: bool = False) -> str:
        """写入文件（append=True 追加）"""
        try:
            target = _safe_write_path(path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            mode = 'a' if append else 'w'
            loop = asyncio.get_event_loop()
            def _write():
                with open(target, mode, encoding='utf-8') as f:
                    f.write(content)
            await loop.run_in_executor(None, _write)
            return f"OK: {path}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def file_edit(path: str, old_string: str, new_string: str) -> str:
        """查找替换文件内容"""
        try:
            target = _safe_write_path(path)
            loop = asyncio.get_event_loop()
            def _edit():
                with open(target, 'r', encoding='utf-8') as f:
                    content = f.read()
                if old_string not in content:
                    return "Error: old_string not found"
                content = content.replace(old_string, new_string, 1)
                with open(target, 'w', encoding='utf-8') as f:
                    f.write(content)
                return f"OK: edited {path}"
            return await loop.run_in_executor(None, _edit)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def dir_list(path: str = ".") -> str:
        """列出目录内容"""
        try:
            target = _safe_read_path(path)
            items = os.listdir(target)
            result = []
            for name in items:
                full = os.path.join(target, name)
                result.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else None
                })
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def dir_create(path: str) -> str:
        """创建目录"""
        try:
            os.makedirs(_safe_write_path(path), exist_ok=True)
            return f"OK: created {path}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def read_json(path: str) -> str:
        """读取JSON知识库"""
        loop = asyncio.get_event_loop()
        def _read():
            with open(_safe_read_path(path), 'r', encoding='utf-8') as f:
                data = json.load(f)
            return json.dumps(data, ensure_ascii=False, indent=2)
        return await loop.run_in_executor(None, _read)

    # ===========================
    # 远程文件传输工具（解决远程服务器无法直接访问客户端文件的限制）
    # ===========================

    @mcp.tool()
    async def file_upload(content_base64: str, filename: str) -> str:
        """将客户端文件上传到服务器。

通过 Base64 编码传输文件内容，适用于远程服务器无法直接访问客户端文件系统的场景。

Args:
    content_base64: 文件的 Base64 编码字符串
    filename: 保存的文件名（如 "个人简历空表.docx"），自动存入 uploads/ 目录

Returns:
    JSON，包含 server_path（后续调用其他工具时使用此路径）和 file_size

用法示例:
    1. 先在客户端读取文件并 Base64 编码（用本地工具）
    2. 调用 file_upload 上传到服务器
    3. 用返回的 server_path 调用 parse_word_form / fill_word_form 等工具
    4. 用 file_download 下载处理结果
"""
        try:
            raw = base64.b64decode(content_base64)
            # 防止路径穿越攻击
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
        """从服务器下载文件（Base64编码返回）。

Args:
    path: 服务器上的文件路径（支持 file_upload 返回的 server_path 或服务器本地路径）

Returns:
    JSON，包含 base64_content（文件的Base64编码）、filename、file_size、mime_type。
    调用方将 base64_content 解码写入本地文件即可。
"""
        try:
            target = _safe_read_path(path)
            filename = os.path.basename(target)
            # 推断 MIME 类型
            ext = os.path.splitext(filename)[1].lower()
            mime_map = {'.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        '.pdf': 'application/pdf', '.txt': 'text/plain',
                        '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg'}
            mime = mime_map.get(ext, 'application/octet-stream')

            loop = asyncio.get_event_loop()
            def _read():
                with open(target, 'rb') as f:
                    return base64.b64encode(f.read()).decode('ascii')
            content = await loop.run_in_executor(None, _read)
            file_size = os.path.getsize(target)

            return json.dumps({
                "status": "ok",
                "filename": filename,
                "file_size": file_size,
                "mime_type": mime,
                "base64_content": content,
                "usage_note": "将 base64_content 解码后写入文件即可得到原始文档。客户端: 先 base64.b64decode 再写入二进制文件。",
            }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

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
            return f"Error: {str(e)}"
