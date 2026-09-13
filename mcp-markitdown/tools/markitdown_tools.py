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
import socket
import logging
import tempfile
import base64
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ===================== 可访问范围配置 =====================

def _env_list(name: str):
    """读取逗号分隔的环境变量为列表"""
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


# 允许访问的域名（支持 *.suffix 通配），默认仅本机域名
# 可用环境变量 FETCH_ALLOWED_HOSTS 覆盖（逗号分隔），例如：*.corp.local,*.intranet.local
_ALLOWED_HOSTS = _env_list("FETCH_ALLOWED_HOSTS") or [
    "localhost",
    "127.0.0.1",
    "::1",
    "*.intranet.local",
]

# 额外放行的 IP 网段（CIDR），用于内网使用了"公网段地址"的场景（可选，逗号分隔，叠加在内网默认规则之上）
# 例如：FETCH_ALLOWED_CIDRS=11.0.0.0/8,30.0.0.0/8
_ALLOWED_CIDRS = _env_list("FETCH_ALLOWED_CIDRS")

_ALLOWED_NETWORKS = []
for _cidr in _ALLOWED_CIDRS:
    try:
        _ALLOWED_NETWORKS.append(ipaddress.ip_network(_cidr, strict=False))
    except ValueError:
        logger.warning("忽略非法的网段配置: %s", _cidr)

# 是否完全跳过 IP 网段校验（默认关闭）：置 1 后不限目标网段，仅建议在可信内网环境使用
_ALLOW_ALL = os.environ.get("FETCH_ALLOW_ALL", "0").strip().lower() in ("1", "true", "yes", "on")

# 是否允许通过 DNS 解析内网域名（默认开启）：域名解析出的所有 IP 都满足放行规则时才放行
_RESOLVE_DNS = os.environ.get("FETCH_RESOLVE_DNS", "1").strip().lower() not in ("0", "false", "no", "off")


def _ip_allowed(ip) -> bool:
    """判断单个 IP 是否允许访问：默认放行所有非公网（私有/特殊用途/保留）网段"""
    if _ALLOW_ALL:
        return True
    if not ip.is_global:
        return True
    return any(ip in net for net in _ALLOWED_NETWORKS if net.version == ip.version)


def _hostname_resolves_allowed(hostname: str) -> bool:
    """域名 DNS 解析：解析出的所有 IP 都满足放行规则时才放行（避免解析到公网）"""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError, UnicodeError):
        return False
    ips = []
    for info in infos:
        addr = (info[4][0] or "").split("%", 1)[0]   # 去掉 IPv6 作用域后缀
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not ips:
        return False
    return all(_ip_allowed(ip) for ip in ips)


def _is_intranet_url(url: str) -> bool:
    """校验URL是否在允许访问的范围内（默认放行全部非公网地址，域名可经 DNS 解析判定）"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False

    # 全局放行模式：不限目标网段
    if _ALLOW_ALL:
        return True

    # 域名白名单检查（支持 *.suffix 通配）
    for allowed in _ALLOWED_HOSTS:
        allowed = allowed.lower()
        if allowed.startswith("*."):
            suffix = allowed[1:]          # ".intranet.local"
            if hostname.endswith(suffix) or hostname == allowed[2:]:
                return True
        elif hostname == allowed:
            return True

    # IP 网段检查（含 IPv6）
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    if ip is not None:
        return _ip_allowed(ip)

    # 域名 DNS 解析检查：解析结果全部为非公网才放行（内网域名服务器的场景）
    if _RESOLVE_DNS:
        return _hostname_resolves_allowed(hostname)
    return False


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
    """将网页内容转换为Markdown（默认仅允许内网URL，可通过环境变量放开）"""
    md = _import_markitdown()
    if md is None:
        return "【错误】markitdown 库未安装。"

    # 安全检查：仅允许访问范围内的URL
    if not _is_intranet_url(url):
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
        description="将网页内容转换为Markdown格式（默认仅允许内网地址，可通过环境变量放开网段）。Args: url(网页地址,必填)"
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
