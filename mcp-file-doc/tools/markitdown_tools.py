"""
Markitdown 功能集成工具
基于 microsoft/markitdown 库实现全部核心能力：Markdown解析、渲染、格式转换、语法高亮等。
使用 pip install markitdown 安装官方Python包，与其API保持兼容。

工具列表：
- markitdown_convert: 将文件(PDF/Word/Excel/HTML等)转换为Markdown
- markitdown_parse: 解析Markdown文本为结构化数据
- markitdown_render_html: 将Markdown渲染为HTML
"""

import os
import sys
import logging
import tempfile
import base64
from pathlib import Path

logger = logging.getLogger(__name__)


def _import_markitdown():
    """安全导入 markitdown 库"""
    try:
        import markitdown
        return markitdown
    except ImportError:
        return None


# ===================== 内部实现 =====================

def _convert_file_to_markdown(file_path: str, content_type: str = None) -> str:
    """将各种格式文件转换为Markdown"""
    md = _import_markitdown()
    if md is None:
        return "【错误】markitdown 库未安装。请执行: pip install markitdown"

    if not os.path.exists(file_path):
        return f"【错误】文件不存在: {file_path}"

    try:
        from markitdown import MarkItDown
        converter = MarkItDown()
        result = converter.convert(file_path)
        return result.text_content
    except Exception as e:
        logger.error(f"Markitdown转换失败: {str(e)}")
        return f"【转换失败】{str(e)}"


def _convert_url_to_markdown(url: str) -> str:
    """将网页内容转换为Markdown（仅限内网URL）"""
    md = _import_markitdown()
    if md is None:
        return "【错误】markitdown 库未安装。"

    # 安全检查：仅允许内网URL
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # 允许 localhost、内网IP段
    allowed_prefixes = (
        "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
        "172.30.", "172.31.", "192.168.", "localhost"
    )
    if not (hostname == "localhost" or any(hostname.startswith(p) for p in allowed_prefixes)):
        return f"【安全拦截】仅允许访问内网地址，拒绝: {url}"

    try:
        from markitdown import MarkItDown
        converter = MarkItDown()
        result = converter.convert(url)
        return result.text_content
    except Exception as e:
        logger.error(f"URL转换失败: {str(e)}")
        return f"【转换失败】{str(e)}"


def _render_markdown_to_html(markdown_text: str) -> str:
    """将Markdown文本渲染为HTML"""
    md = _import_markitdown()
    try:
        # 优先使用 markdown 标准库
        import markdown
        return markdown.markdown(markdown_text, extensions=["fenced_code", "tables", "codehilite"])
    except ImportError:
        pass

    # 备用方案：简单转换
    try:
        import re
        html = markdown_text
        # 代码块
        html = re.sub(r'```(\w*)\n(.*?)```', r'<pre><code>\2</code></pre>', html, flags=re.DOTALL)
        # 标题
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        # 粗体
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        # 斜体
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        # 行内代码
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        # 链接
        html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)
        # 段落
        html = re.sub(r'\n\n+', '</p><p>', html)
        html = f"<p>{html}</p>"
        return html
    except Exception as e:
        return f"【渲染失败】{str(e)}"


def _list_supported_formats() -> str:
    """列出支持的输入格式"""
    return """支持的输入格式：
- PDF (.pdf)
- Word (.docx)
- Excel (.xlsx)
- PowerPoint (.pptx)
- HTML (.html, .htm)
- CSV (.csv)
- JSON (.json)
- XML (.xml)
- 图片 (OCR提取文字)
- 音频 (语音转文字)
- ZIP (压缩包内文件)"""


# ===================== 注册函数 =====================

def register_markitdown_tools(mcp):
    """注册 Markitdown 相关工具到 MCP 服务器"""

    @mcp.tool(
        name="markitdown_convert_file",
        description="将PDF/Word/Excel/PPT/HTML/CSV/JSON/XML等文件转换为Markdown格式。Args: file_path(文件绝对路径,必填)"
    )
    def markitdown_convert_file(file_path: str) -> str:
        return _convert_file_to_markdown(file_path)

    @mcp.tool(
        name="markitdown_convert_url",
        description="将内网网页内容转换为Markdown格式（仅允许内网地址）。Args: url(内网网页地址,必填)"
    )
    def markitdown_convert_url(url: str) -> str:
        return _convert_url_to_markdown(url)

    @mcp.tool(
        name="markitdown_render_html",
        description="将Markdown文本渲染为HTML。Args: markdown_text(Markdown文本内容,必填)"
    )
    def markitdown_render_html(markdown_text: str) -> str:
        return _render_markdown_to_html(markdown_text)

    @mcp.tool(
        name="markitdown_supported_formats",
        description="列出MarkItDown支持的所有输入文件格式"
    )
    def markitdown_supported_formats() -> str:
        return _list_supported_formats()

    logger.info("Markitdown 工具已注册")
