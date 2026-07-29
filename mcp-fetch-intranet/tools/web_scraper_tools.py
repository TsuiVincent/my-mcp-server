"""
内网网页抓取工具
支持HTML内容提取、链接解析、资源下载，仅允许访问内网指定域名。
包含请求频率控制与错误处理机制。

工具列表：
- intranet_fetch_html: 抓取内网网页HTML内容
- intranet_extract_links: 提取网页中所有链接
- intranet_download_resource: 下载网页资源(图片/CSS/JS等)
- intranet_fetch_json: 抓取内网API返回的JSON数据
"""

import os
import re
import json
import base64
import time
import hashlib
import logging
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse
from collections import defaultdict

logger = logging.getLogger(__name__)

# ===================== 配置 =====================

# 内网允许的域名/IP前缀
_ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "*.intranet.local",
]

# 内网允许的IP段前缀
_ALLOWED_IP_PREFIXES = (
    "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
    "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
    "172.30.", "172.31.", "192.168.", "127."
)

# 请求频率控制：每个域名每秒最大请求数
_RATE_LIMIT = 5
_RATE_WINDOW = 1.0  # 1秒窗口

# 请求计数器：{hostname: [(timestamp, ...)]}
_request_timestamps = defaultdict(list)

# 资源最大下载大小（10MB）
_MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024

# 允许的资源文件扩展名
_ALLOWED_EXTENSIONS = {".html", ".htm", ".css", ".js", ".json", ".xml",
                        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                        ".pdf", ".txt", ".csv", ".md", ".woff", ".woff2",
                        ".ttf", ".eot"}


def _import_httpx():
    """安全导入 httpx"""
    try:
        import httpx
        return httpx
    except ImportError:
        return None


# ===================== 安全校验 =====================

def _is_intranet_url(url: str) -> bool:
    """校验URL是否为内网地址"""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    # localhost
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return True

    # IP段检查
    if hostname.replace('.', '').isdigit():
        return any(hostname.startswith(prefix) for prefix in _ALLOWED_IP_PREFIXES)

    # 域名白名单检查
    for allowed in _ALLOWED_HOSTS:
        if allowed.startswith("*."):
            suffix = allowed[2:]
            if hostname.endswith(suffix):
                return True
        elif hostname == allowed:
            return True

    return False


def _check_rate_limit(hostname: str) -> bool:
    """请求频率控制"""
    now = time.time()
    # 清理过期记录
    _request_timestamps[hostname] = [
        t for t in _request_timestamps[hostname]
        if now - t < _RATE_WINDOW
    ]
    if len(_request_timestamps[hostname]) >= _RATE_LIMIT:
        return False
    _request_timestamps[hostname].append(now)
    return True


def _is_allowed_resource(url: str) -> bool:
    """检查资源扩展名是否允许下载"""
    path = urlparse(url).path.lower()
    ext = os.path.splitext(path)[1]
    return ext in _ALLOWED_EXTENSIONS if ext else True


# ===================== 工具实现 =====================

def _fetch_html(url: str, timeout: int = 10) -> str:
    """抓取内网网页HTML内容"""
    if not _is_intranet_url(url):
        return f"【安全拦截】仅允许访问内网地址，拒绝: {url}"

    hostname = urlparse(url).hostname
    if not _check_rate_limit(hostname):
        return f"【频率限制】请求过于频繁，请稍后再试 ({hostname})"

    httpx_mod = _import_httpx()
    if httpx_mod is None:
        return "【错误】httpx 库未安装。请执行: pip install httpx"

    try:
        with httpx_mod.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"【提示】非HTML内容 (Content-Type: {content_type})，返回内容前200字符:\n{response.text[:200]}"

            return response.text
    except httpx_mod.HTTPStatusError as e:
        return f"【HTTP错误】状态码 {e.response.status_code}: {url}"
    except httpx_mod.TimeoutException:
        return f"【超时】请求超时 ({timeout}s): {url}"
    except httpx_mod.ConnectError:
        return f"【连接失败】无法连接到: {url}"
    except Exception as e:
        logger.error(f"抓取失败: {str(e)}")
        return f"【抓取失败】{str(e)}"


def _extract_links(html: str, base_url: str = "") -> str:
    """提取HTML中的所有链接"""
    try:
        link_pattern = r'<a\s+(?:[^>]*?\s+)?href="([^"]*)"'
        src_pattern = r'<[^>]+(?:src|href)="([^"]*)"'

        raw_links = re.findall(link_pattern, html, re.IGNORECASE)
        resources = re.findall(src_pattern, html, re.IGNORECASE)

        all_links = list(set(raw_links + resources))
        # 过滤空链接和锚点
        all_links = [l for l in all_links if l.strip() and not l.startswith("#") and not l.startswith("javascript:")]

        result_lines = ["【提取的链接列表】"]
        result_lines.append(f"共找到 {len(all_links)} 个链接:\n")

        internal_links = []
        external_links = []

        for link in sorted(all_links):
            full_url = urljoin(base_url, link) if base_url else link
            if _is_intranet_url(full_url):
                internal_links.append((link, full_url))
            else:
                external_links.append(link)

        if internal_links:
            result_lines.append("--- 内网链接 ---")
            for original, full in internal_links[:100]:
                result_lines.append(f"  {original} -> {full}")

        if external_links:
            result_lines.append(f"\n--- 外部链接（仅参考，禁止访问） ({len(external_links)}个) ---")

        return "\n".join(result_lines)
    except Exception as e:
        logger.error(f"链接提取失败: {str(e)}")
        return f"【提取失败】{str(e)}"


def _download_resource(url: str, save_dir: str = "") -> str:
    """下载内网资源文件"""
    if not _is_intranet_url(url):
        return f"【安全拦截】仅允许访问内网地址，拒绝: {url}"

    if not _is_allowed_resource(url):
        return f"【拒绝】不允许的文件类型: {url}"

    hostname = urlparse(url).hostname
    if not _check_rate_limit(hostname):
        return f"【频率限制】请求过于频繁，请稍后再试"

    httpx_mod = _import_httpx()
    if httpx_mod is None:
        return "【错误】httpx 库未安装。"

    try:
        with httpx_mod.Client(timeout=30, follow_redirects=True) as client:
            # 先检查文件大小
            head_resp = client.head(url)
            content_length = int(head_resp.headers.get("content-length", 0))
            if content_length > _MAX_DOWNLOAD_SIZE:
                return f"【拒绝】文件过大 ({content_length} bytes)，最大允许 {_MAX_DOWNLOAD_SIZE} bytes"

            response = client.get(url)
            response.raise_for_status()

            # 确定保存路径
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "download"
            if not os.path.splitext(filename)[1]:
                # 从Content-Type推断扩展名
                ct = response.headers.get("content-type", "")
                if "json" in ct:
                    filename += ".json"
                elif "html" in ct:
                    filename += ".html"
                elif "css" in ct:
                    filename += ".css"
                elif "javascript" in ct:
                    filename += ".js"
                else:
                    filename += ".bin"

            if save_dir:
                os.makedirs(save_dir, exist_ok=True)
                filepath = os.path.join(save_dir, filename)
            else:
                # 默认保存到临时目录
                download_dir = os.path.join(tempfile.gettempdir(), "intranet_downloads")
                os.makedirs(download_dir, exist_ok=True)
                filepath = os.path.join(download_dir, filename)

            with open(filepath, "wb") as f:
                f.write(response.content)

            return f"【下载成功】\nURL: {url}\n保存位置: {filepath}\n大小: {len(response.content)} bytes"
    except Exception as e:
        logger.error(f"下载失败: {str(e)}")
        return f"【下载失败】{str(e)}"


def _fetch_json(url: str, timeout: int = 10) -> str:
    """抓取内网API返回的JSON数据并格式化"""
    if not _is_intranet_url(url):
        return f"【安全拦截】仅允许访问内网地址: {url}"

    hostname = urlparse(url).hostname
    if not _check_rate_limit(hostname):
        return f"【频率限制】请求过于频繁，请稍后再试"

    httpx_mod = _import_httpx()
    if httpx_mod is None:
        return "【错误】httpx 库未安装。"

    try:
        with httpx_mod.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            data = response.json()
            return json.dumps(data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return f"【格式错误】返回内容不是有效JSON，原始内容前200字符:\n{response.text[:200]}"
    except Exception as e:
        logger.error(f"JSON抓取失败: {str(e)}")
        return f"【抓取失败】{str(e)}"


# ===================== 正文提取 =====================

# 非正文标签（导航/侧边栏/页脚/广告/脚本/样式）
_CONTENT_EXCLUDE_TAGS = {
    "nav", "header", "footer", "aside", "script", "style", "noscript",
    "iframe", "object", "embed", "svg", "canvas", "video", "audio",
    "link", "meta", "base",
}

# 非正文 class/id 关键词
_CONTENT_EXCLUDE_PATTERNS = re.compile(
    r"(nav(igation|bar|menu)?|sidebar|side-bar|footer|header|banner|"
    r"breadcrumb|pagination|toolbar|toc|table-of-contents|"
    r"comment|share|social|ad(vertisement|s)?|popup|overlay|modal|"
    r"copyright|disclaimer|related|recommended|widget)",
    re.IGNORECASE
)

# 正文容器 class/id 关键词（优先保留）
_CONTENT_INCLUDE_PATTERNS = re.compile(
    r"(content|article|post|main|body|entry|text|document|"
    r"markdown|readme|description|detail|summary)",
    re.IGNORECASE
)


def _clean_text(text: str) -> str:
    """清理文本：合并空白、去除首尾空格"""
    return re.sub(r'\s+', ' ', text).strip()


def _extract_main_content(html: str) -> str:
    """
    从HTML中提取正文内容。
    策略：优先查找正文容器，否则使用消减法去除非正文区域。
    """
    try:
        # 尝试用 html.parser 解析（标准库，无额外依赖）
        from html.parser import HTMLParser

        class ContentExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self._result_parts = []
                self._skip_depth = 0
                self._include_depth = 0
                self._tag_stack = []
                self._tag_exclude_depth = {}  # tag_depth -> skip_depth value when entered

            def handle_starttag(self, tag, attrs):
                tag_lower = tag.lower()
                attrs_dict = dict(attrs)
                cls = attrs_dict.get("class", "")
                id_val = attrs_dict.get("id", "")
                combined = f"{cls} {id_val}"

                if tag_lower in _CONTENT_EXCLUDE_TAGS:
                    self._skip_depth += 1
                    return

                # 检查 class/id 是否为非正文
                if _CONTENT_EXCLUDE_PATTERNS.search(combined):
                    self._skip_depth += 1
                    return

                # 检查 class/id 是否为正文容器（降低排除权重）
                if _CONTENT_INCLUDE_PATTERNS.search(combined):
                    self._include_depth += 1

                self._tag_stack.append(tag_lower)

            def handle_endtag(self, tag):
                tag_lower = tag.lower()
                if self._tag_stack:
                    # 如果是排除标签末尾，减少排除深度
                    if self._skip_depth > 0:
                        self._skip_depth -= 1

            def handle_data(self, data):
                if self._skip_depth > 0:
                    return
                text = _clean_text(data)
                if text and len(text) > 1:
                    self._result_parts.append(text)

        extractor = ContentExtractor()
        extractor.feed(html)
        extractor.close()

        result = "\n".join(extractor._result_parts)
        if len(result) < 100:
            # 降级：返回原始HTML的纯文本版本
            clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL | re.IGNORECASE)
            clean = re.sub(r'<[^>]+>', ' ', clean)
            clean = re.sub(r'&nbsp;', ' ', clean)
            clean = re.sub(r'&[a-z]+;', ' ', clean, flags=re.IGNORECASE)
            clean = re.sub(r'\s+', '\n', clean).strip()
            lines = [l.strip() for l in clean.splitlines() if l.strip() and len(l.strip()) > 10]
            result = "\n".join(lines[:500])

        return result
    except Exception as e:
        logger.warning(f"正文提取失败: {e}，返回原文")
        # 最终降级
        clean = re.sub(r'<[^>]+>', ' ', html)
        clean = re.sub(r'\s+', '\n', clean).strip()
        return clean


# ===================== 递归爬取 =====================

def _crawl_site(
    start_url: str,
    max_depth: int = 3,
    max_pages: int = 50,
    timeout: int = 15,
) -> str:
    """
    递归爬取站内页面，返回每页的正文汇总。
    只爬取同一域名下的内网链接。
    """
    if not _is_intranet_url(start_url):
        return f"【安全拦截】仅允许访问内网地址，拒绝: {start_url}"

    httpx_mod = _import_httpx()
    if httpx_mod is None:
        return "【错误】httpx 库未安装。"

    start_host = urlparse(start_url).hostname or ""
    start_scheme = urlparse(start_url).scheme
    base_origin = f"{start_scheme}://{start_host}"

    # 去重集合
    visited = set()
    results = []
    queue = [(start_url, 0)]  # (url, depth)

    try:
        with httpx_mod.Client(timeout=timeout, follow_redirects=True) as client:
            while queue and len(visited) < max_pages:
                url, depth = queue.pop(0)
                if url in visited:
                    continue
                if depth > max_depth:
                    continue
                visited.add(url)

                # 频率控制
                hostname = urlparse(url).hostname
                if not _check_rate_limit(hostname or ""):
                    results.append(f"【跳过-频率限制】{url}")
                    continue

                try:
                    resp = client.get(url)
                    status = resp.status_code
                    if status != 200:
                        results.append(f"[{status}] {url} (跳过)")
                        continue

                    html = resp.text
                    content = _extract_main_content(html)

                    # 从正文摘要中取前500字符作为预览
                    preview = content[:500].replace('\n', ' | ')
                    results.append(f"## [{depth}] {url}\n{preview}\n")

                    # 如果未达到最大深度，提取链接继续爬
                    if depth < max_depth and len(visited) < max_pages:
                        links = _extract_links_internal(html, url)
                        # 只保留内网同域链接
                        for link in links:
                            if link not in visited and _is_intranet_url(link):
                                parsed = urlparse(link)
                                if parsed.hostname == start_host:
                                    queue.append((link, depth + 1))

                except httpx_mod.HTTPStatusError as e:
                    results.append(f"[{e.response.status_code}] {url} (HTTP错误)")
                except httpx_mod.TimeoutException:
                    results.append(f"[超时] {url}")
                except Exception as e:
                    results.append(f"[错误] {url}: {e}")

    except Exception as e:
        return f"【爬取异常】{e}"

    header = (
        f"【爬取完成】\n"
        f"起始URL: {start_url}\n"
        f"已访问: {len(visited)} 页\n"
        f"最大深度: {max_depth}\n"
        f"{'='*50}\n\n"
    )
    return header + "\n".join(results)


def _extract_links_internal(html: str, base_url: str) -> list:
    """提取HTML中的同域链接列表（简化版，供crawl/map使用）"""
    link_pattern = r'<a\s+(?:[^>]*?\s+)?href="([^"]*)"'
    raw_links = re.findall(link_pattern, html, re.IGNORECASE)
    links = []
    for link in raw_links:
        if not link.strip() or link.startswith("#") or link.startswith("javascript:"):
            continue
        if link.startswith("mailto:") or link.startswith("tel:"):
            continue
        full_url = urljoin(base_url, link)
        parsed = urlparse(full_url)
        if parsed.scheme not in ("http", "https"):
            continue
        links.append(full_url)
    return list(set(links))


# ===================== 站点URL发现 =====================

def _map_site_urls(url: str, max_urls: int = 200) -> str:
    """
    发现站点所有可访问的URL。
    优先级: sitemap.xml > sitemap.xml.gz > HTML链接提取
    """
    if not _is_intranet_url(url):
        return f"【安全拦截】仅允许访问内网地址，拒绝: {url}"

    httpx_mod = _import_httpx()
    if httpx_mod is None:
        return "【错误】httpx 库未安装。"

    discovered = set()
    source = ""

    parsed_start = urlparse(url)
    base_origin = f"{parsed_start.scheme}://{parsed_start.hostname}"

    try:
        with httpx_mod.Client(timeout=15, follow_redirects=True) as client:
            # 优先尝试 sitemap.xml
            sitemap_urls = [
                f"{base_origin}/sitemap.xml",
                f"{base_origin}/sitemap.xml.gz",
                f"{base_origin}/sitemap_index.xml",
            ]
            for sm_url in sitemap_urls:
                try:
                    resp = client.get(sm_url)
                    if resp.status_code == 200:
                        text = resp.text
                        # 检查是否为gzip
                        if sm_url.endswith(".gz") or resp.headers.get("content-type", "") == "application/gzip":
                            import gzip
                            try:
                                text = gzip.decompress(resp.content).decode("utf-8")
                            except Exception:
                                pass
                        # 提取URL
                        url_matches = re.findall(r'<loc>(.*?)</loc>', text)
                        for u in url_matches:
                            discovered.add(u.strip())
                        if url_matches:
                            source = f"sitemap ({sm_url})"
                            break
                except Exception:
                    continue

            # 降级: 请求首页并提取链接
            if not discovered:
                source = "首页链接提取"
                resp = client.get(url)
                if resp.status_code == 200:
                    html = resp.text
                    links = _extract_links_internal(html, url)
                    for link in links[:max_urls]:
                        if _is_intranet_url(link):
                            discovered.add(link)

            # 尝试解析 sitemap 索引（多层）
            sitemap_indices = [u for u in discovered if "sitemap" in u.lower()]
            if sitemap_indices and len(discovered) < 20:
                for si_url in sitemap_indices[:3]:
                    try:
                        resp = client.get(si_url)
                        if resp.status_code == 200:
                            url_matches = re.findall(r'<loc>(.*?)</loc>', resp.text)
                            for u in url_matches:
                                discovered.add(u.strip())
                    except Exception:
                        continue

    except Exception as e:
        return f"【URL发现失败】{e}"

    # 分类
    pages = []
    resources = []

    resource_exts = {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg",
                     ".ico", ".woff", ".woff2", ".ttf", ".eot", ".pdf",
                     ".zip", ".tar", ".gz", ".mp4", ".webm", ".mp3"}

    for u in sorted(discovered):
        path = urlparse(u).path.lower()
        ext = os.path.splitext(path)[1]
        if ext in resource_exts:
            resources.append(u)
        else:
            pages.append(u)

    result = {
        "status": "ok",
        "source": source,
        "total_discovered": len(discovered),
        "pages": pages[:max_urls],
        "page_count": len(pages),
        "resources": resources[:100] if len(resources) <= 100 else [],
        "resource_count": len(resources),
    }

    if len(resources) > 100:
        result["resources_truncated"] = True

    return json.dumps(result, ensure_ascii=False, indent=2)


def _allow_host(host: str) -> str:
    """添加允许访问的内网主机（需要管理员权限的场景）"""
    if host not in _ALLOWED_HOSTS:
        _ALLOWED_HOSTS.append(host)
        return f"【已添加】{host} 已加入内网白名单。当前白名单: {_ALLOWED_HOSTS}"
    return f"【已存在】{host} 已在白名单中"


# ===================== 注册函数 =====================

def register_web_scraper_tools(mcp):
    """注册内网网页抓取工具到 MCP 服务器"""

    @mcp.tool(
        name="intranet_fetch_html",
        description="抓取内网网页HTML内容。仅允许访问内网地址(127.0.0.1/10.x/172.16-31.x/192.168.x/localhost)。Args: url(网页地址,必填), timeout(超时秒数,默认10)"
    )
    def intranet_fetch_html(url: str, timeout: int = 10) -> str:
        return _fetch_html(url, timeout)

    @mcp.tool(
        name="intranet_extract_links",
        description="从HTML内容中提取所有链接，分类为内网/外部链接。Args: html(HTML内容,必填), base_url(基础URL用于解析相对路径,可选)"
    )
    def intranet_extract_links(html: str, base_url: str = "") -> str:
        return _extract_links(html, base_url)

    @mcp.tool(
        name="intranet_download_resource",
        description="下载内网资源文件(图片/CSS/JS/文档等)，最大10MB，同时返回Base64编码内容。Args: url(资源地址,必填), save_dir(服务器保存目录,可选,默认临时目录)"
    )
    def intranet_download_resource(url: str, save_dir: str = "") -> str:
        msg = _download_resource(url, save_dir)
        try:
            result_line = msg.splitlines()[0] if msg else ""
            if "【下载成功】" in result_line:
                for line in msg.splitlines():
                    if line.startswith("保存位置:"):
                        filepath = line.split(":", 1)[1].strip()
                        if os.path.exists(filepath):
                            with open(filepath, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("ascii")
                            return json.dumps({
                                "message": msg,
                                "download_base64": b64,
                                "filename": os.path.basename(filepath),
                                "file_size": os.path.getsize(filepath),
                                "usage": "将 download_base64 解码后写入文件即可",
                            }, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return msg

    @mcp.tool(
        name="intranet_fetch_json",
        description="抓取内网API返回的JSON数据并格式化输出。Args: url(API地址,必填), timeout(超时秒数,默认10)"
    )
    def intranet_fetch_json(url: str, timeout: int = 10) -> str:
        return _fetch_json(url, timeout)

    # ================================================================
    # 新增工具：正文提取 / 递归爬取 / URL发现
    # ================================================================

    @mcp.tool(
        name="intranet_fetch_content",
        description="抓取内网网页并提取正文内容（自动去除导航/侧边栏/页脚/广告/脚本/样式）。返回纯文本正文。Args: url(网页地址,必填), timeout(超时秒数,默认10)"
    )
    def intranet_fetch_content(url: str, timeout: int = 10) -> str:
        """抓取内网网页正文（去除非正文元素）"""
        if not _is_intranet_url(url):
            return f"【安全拦截】仅允许访问内网地址，拒绝: {url}"
        hostname = urlparse(url).hostname
        if not _check_rate_limit(hostname or ""):
            return f"【频率限制】请求过于频繁，请稍后再试 ({hostname})"

        httpx_mod = _import_httpx()
        if httpx_mod is None:
            return "【错误】httpx 库未安装。"

        try:
            with httpx_mod.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                content = _extract_main_content(resp.text)
                return json.dumps({
                    "status": "ok",
                    "url": str(resp.url),
                    "content_length": len(content),
                    "extracted_text": content[:20000],
                    "truncated": len(content) > 20000,
                }, ensure_ascii=False, indent=2)
        except httpx_mod.HTTPStatusError as e:
            return _make_error_json("HTTP_ERROR", f"状态码 {e.response.status_code}")
        except httpx_mod.TimeoutException:
            return _make_error_json("TIMEOUT", f"请求超时 ({timeout}s)")
        except Exception as e:
            return _make_error_json("FETCH_ERROR", str(e))

    @mcp.tool(
        name="intranet_crawl",
        description="递归爬取内网站点所有页面并提取正文，返回每页内容汇总。仅爬取同域名链接。Args: url(起始URL,必填), max_depth(最大深度,默认3), max_pages(最大页数,默认50), timeout(单页超时秒数,默认15)"
    )
    def intranet_crawl(
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        timeout: int = 15,
    ) -> str:
        return _crawl_site(url, max_depth=max_depth, max_pages=max_pages, timeout=timeout)

    @mcp.tool(
        name="intranet_map_urls",
        description="发现内网站点所有可访问的URL（优先解析sitemap.xml，降级为首页链接提取）。返回分类后的页面和资源列表。Args: url(站点URL,必填), max_urls(最大URL数,默认200)"
    )
    def intranet_map_urls(url: str, max_urls: int = 200) -> str:
        return _map_site_urls(url, max_urls=max_urls)

    logger.info("内网网页抓取工具已注册")


def _make_error_json(code: str, message: str) -> str:
    return json.dumps({"status": "error", "code": code, "message": message}, ensure_ascii=False)
