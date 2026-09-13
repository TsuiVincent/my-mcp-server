"""
网页爬虫工具（静态抓取 + 无头浏览器渲染）

与 web_scraper_tools.py 的区别：
- web_scraper_tools：面向"内网"的原子抓取能力（取名较早，保持兼容）
- spider_tools：面向"通用网页爬取"的增强能力，静态优先、SPA 自动升级渲染、并发爬取

工具列表：
- web_fetch:        智能抓取单页（静态优先，检测到 SPA/空壳自动升级渲染）
- web_crawl:        并发递归爬取站点，支持渲染兜底与 Markdown 落盘
- web_render_fetch: 强制使用无头浏览器渲染抓取（JS 动态页面）
- web_extract:      结构化提取（标题/摘要/正文/链接/表格/图片/标题层级）
- web_login_state:  管理登录态（cookies/headers），供上述工具复用

依赖：
- 静态抓取：httpx（必需）
- 结构化提取：beautifulsoup4（可选，缺失时降级为正则）
- JS 渲染：playwright + chromium（可选，构建镜像时 WITH_RENDER=1 开启）
"""

import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

from tools.web_scraper_tools import (
    _is_intranet_url,
    _check_rate_limit,
    _extract_main_content,
    _extract_links_internal,
    _clean_text,
    _import_httpx,
)

logger = logging.getLogger(__name__)

# ===================== 配置 =====================

# 单页正文返回的最大字符数
_DEFAULT_MAX_CHARS = int(os.environ.get("WEB_FETCH_MAX_CHARS", "60000") or 60000)

# 浏览器渲染并发上限
_RENDER_CONCURRENCY = int(os.environ.get("WEB_RENDER_CONCURRENCY", "2") or 2)

# 抓取用的 User-Agent（可用环境变量覆盖）
_USER_AGENT = os.environ.get(
    "FETCH_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 WebCrawler/1.0",
)

# 是否校验 HTTPS 证书（内网自签证书常见，默认关闭校验）
_VERIFY_TLS = os.environ.get("FETCH_VERIFY_TLS", "0") == "1"

# SPA / 空壳页面特征
_SPA_SHELL_PATTERNS = [
    r'<div[^>]+id=["\'](app|root|main-app)["\'][^>]*>\s*</div>',
]
_SPA_NOSCRIPT_HINTS = [
    "you need to enable javascript",
    "please enable javascript",
    "javascript is disabled",
    "enable javascript to",
    "需要启用 javascript",
    "请开启 javascript",
    "请启用 javascript",
]

# 登录页 URL 特征
_LOGIN_URL_HINTS = ("login", "signin", "sign-in", "sso", "auth", "passport")


# ===================== 通用工具函数 =====================

def _err(code: str, message: str) -> str:
    return json.dumps({"status": "error", "code": code, "message": message}, ensure_ascii=False)


def _extract_title(html: str) -> str:
    """提取 <title> 文本"""
    if not html:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return _clean_text(re.sub(r"<[^>]+>", "", m.group(1)))


def _looks_like_spa_shell(html: str, text: str) -> bool:
    """判断是否为需要 JS 渲染的空壳页面"""
    lowered = html.lower()
    for pat in _SPA_SHELL_PATTERNS:
        if re.search(pat, lowered):
            return True
    low_text = (text or "").lower()
    if any(hint in low_text for hint in _SPA_NOSCRIPT_HINTS):
        return True
    # 正文极短但 HTML 体积不小（典型 SPA 外壳）
    if len(text or "") < 200 and len(html) > 2000:
        return True
    return False


def _looks_like_login(url: str) -> bool:
    """判断 URL 是否像登录页"""
    path = (urlparse(url).path or "").lower()
    query = (urlparse(url).query or "").lower()
    combined = f"{path}?{query}"
    return any(hint in combined for hint in _LOGIN_URL_HINTS)


# ===================== 登录态管理 =====================

def _state_path(base_dir: str, name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name or "default")
    return Path(base_dir) / "browser_state" / f"{safe}.json"


def _load_state(base_dir: str, name: str) -> dict:
    """读取登录态；不存在时返回空 dict"""
    if not name:
        return {}
    p = _state_path(base_dir, name)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("登录态读取失败 %s: %s", p, e)
        return {}


def _normalize_cookies(raw) -> list:
    """把多种形式的 cookie 归一到 playwright 可用的列表结构"""
    if not raw:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return []
    if isinstance(data, dict):
        # {"name": "x", "value": "y"} 或 {"x": "y"}
        if "name" in data and "value" in data:
            data = [data]
        else:
            data = [{"name": k, "value": str(v)} for k, v in data.items()]
    out = []
    for c in data or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        item = {"name": str(c["name"]), "value": str(c.get("value", ""))}
        for k in ("domain", "path", "url", "expires", "httpOnly", "secure", "sameSite"):
            if c.get(k):
                item[k] = c[k]
        out.append(item)
    return out


def _cookie_dict(cookies: list) -> dict:
    return {c["name"]: c["value"] for c in cookies if c.get("name")}


# ===================== 静态抓取 =====================

def _static_fetch(url: str, timeout: int = 20, state: dict = None) -> dict:
    """同步静态抓取（调用方用 asyncio.to_thread 包裹）"""
    httpx_mod = _import_httpx()
    if httpx_mod is None:
        return {"ok": False, "error": "NO_HTTPX", "message": "httpx 未安装"}

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if state and state.get("headers"):
        headers.update(state["headers"])

    cookies = _cookie_dict(_normalize_cookies(state.get("cookies"))) if state else {}

    try:
        with httpx_mod.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            cookies=cookies or None,
            verify=_VERIFY_TLS,
        ) as client:
            resp = client.get(url)
            resp.encoding = resp.encoding or "utf-8"
            return {
                "ok": True,
                "html": resp.text,
                "final_url": str(resp.url),
                "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "encoding": resp.encoding or "",
            }
    except Exception as e:
        logger.warning("静态抓取失败 %s: %s", url, e)
        return {"ok": False, "error": "FETCH_ERROR", "message": str(e)}


# ===================== 无头浏览器渲染 =====================

_render_state = {
    "browser": None,
    "playwright": None,
    "lock": None,
    "sem": None,
    "failed": False,
}


def _render_enabled() -> bool:
    return os.environ.get("WITH_RENDER", "0") == "1"


def _get_render_sem() -> asyncio.Semaphore:
    if _render_state["sem"] is None:
        _render_state["sem"] = asyncio.Semaphore(_RENDER_CONCURRENCY)
    return _render_state["sem"]


async def _get_browser():
    """懒启动共享 Chromium 实例"""
    if _render_state["browser"] is not None:
        return _render_state["browser"]
    if _render_state["failed"]:
        return None
    if _render_state["lock"] is None:
        _render_state["lock"] = asyncio.Lock()
    async with _render_state["lock"]:
        if _render_state["browser"] is not None:
            return _render_state["browser"]
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("playwright 未安装，JS 渲染不可用（构建镜像时请设置 WITH_RENDER=1）")
            _render_state["failed"] = True
            return None
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--hide-scrollbars",
                ],
            )
            _render_state["playwright"] = pw
            _render_state["browser"] = browser
            logger.info("Chromium 渲染引擎已启动")
            return browser
        except Exception as e:
            logger.error("启动 Chromium 失败: %s", e)
            _render_state["failed"] = True
            return None


async def _render_page(
    url: str,
    timeout: int = 30,
    wait_until: str = "domcontentloaded",
    wait_selector: str = "",
    state: dict = None,
    block_heavy: bool = True,
    screenshot: bool = False,
) -> dict:
    """用 Chromium 渲染页面，返回原始 HTML"""
    if not _render_enabled():
        return {
            "ok": False,
            "error": "RENDER_DISABLED",
            "message": "服务未启用 JS 渲染（需以 WITH_RENDER=1 构建并启动）",
        }
    browser = await _get_browser()
    if browser is None:
        return {"ok": False, "error": "RENDER_UNAVAILABLE", "message": "Chromium 渲染引擎不可用"}

    sem = _get_render_sem()
    async with sem:
        ctx = None
        try:
            ctx_kwargs = {"user_agent": _USER_AGENT, "ignore_https_errors": not _VERIFY_TLS}
            if state and state.get("headers"):
                ctx_kwargs["extra_http_headers"] = state["headers"]
            ctx = await browser.new_context(**ctx_kwargs)

            # 注入 cookie（缺少 domain/url 时用目标 url 兜底）
            if state and state.get("cookies"):
                cookies = []
                for c in _normalize_cookies(state["cookies"]):
                    if not c.get("domain") and not c.get("url"):
                        c["url"] = url
                    cookies.append(c)
                try:
                    await ctx.add_cookies(cookies)
                except Exception as e:
                    logger.warning("注入 cookie 失败: %s", e)

            if block_heavy:
                async def _route_handler(route):
                    try:
                        if route.request.resource_type in ("image", "media", "font"):
                            await route.abort()
                        else:
                            await route.continue_()
                    except Exception:
                        pass

                await ctx.route("**/*", _route_handler)

            page = await ctx.new_page()
            resp = None
            try:
                resp = await page.goto(url, timeout=timeout * 1000, wait_until=wait_until)
            except Exception as e:
                # 超时也尝试返回已渲染的部分内容
                logger.warning("页面加载未如期完成(%s): %s", url, e)
                try:
                    html_partial = await page.content()
                    if len(html_partial) < 500:
                        return {"ok": False, "error": "RENDER_TIMEOUT", "message": str(e)}
                except Exception:
                    return {"ok": False, "error": "RENDER_TIMEOUT", "message": str(e)}

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=timeout * 1000)
                except Exception:
                    logger.warning("等待元素超时: %s", wait_selector)

            result = {
                "ok": True,
                "html": await page.content(),
                "final_url": page.url,
                "status": (resp.status if resp else 0) or 0,
                "title": await page.title(),
            }
            if screenshot:
                try:
                    shot = await page.screenshot(full_page=True)
                    import base64 as _b64
                    result["screenshot_base64"] = _b64.b64encode(shot).decode("ascii")
                except Exception as e:
                    logger.warning("截图失败: %s", e)
            return result
        except Exception as e:
            logger.error("渲染失败 %s: %s", url, e)
            return {"ok": False, "error": "RENDER_ERROR", "message": str(e)}
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass


# ===================== 智能抓取核心 =====================

async def _smart_fetch(
    url: str,
    render: str = "auto",
    timeout: int = 20,
    state_name: str = "",
    base_dir: str = "",
    wait_selector: str = "",
) -> dict:
    """
    先静态抓取，必要时升级为浏览器渲染。
    返回统一结构：html/final_url/status/title/text/render_used/diagnostics
    """
    state = _load_state(base_dir, state_name)
    diag = {}

    static = await asyncio.to_thread(_static_fetch, url, timeout, state)
    diag["static_ok"] = static.get("ok", False)
    if not static.get("ok"):
        diag["static_error"] = static.get("message", "")

    html = static.get("html", "") if static.get("ok") else ""
    status = static.get("status", 0)
    final_url = static.get("final_url", url)
    title = ""
    text = _extract_main_content(html) if html else ""
    is_spa = _looks_like_spa_shell(html, text) if html else False

    want_render = render == "always" or (render == "auto" and (is_spa or not html))
    render_used = "static" if html else "none"

    if want_render:
        if _render_enabled():
            rendered = await _render_page(
                url, timeout=max(timeout, 30), wait_until="domcontentloaded",
                wait_selector=wait_selector, state=state,
            )
            if rendered.get("ok"):
                html = rendered["html"]
                final_url = rendered.get("final_url", final_url)
                status = rendered.get("status") or status
                title = rendered.get("title", "")
                text = _extract_main_content(html)
                is_spa = _looks_like_spa_shell(html, text)
                render_used = "chromium"
            else:
                diag["render_code"] = rendered.get("error")
                diag["render_error"] = rendered.get("message")
        else:
            diag["render_hint"] = "页面疑似需要 JS 渲染，但服务未启用渲染（需以 WITH_RENDER=1 构建）"

    if not title:
        title = _extract_title(html)

    return {
        "html": html,
        "final_url": final_url,
        "status": status,
        "title": title,
        "text": text,
        "is_spa": is_spa,
        "render_used": render_used,
        "encoding": static.get("encoding", ""),
        "content_type": static.get("content_type", ""),
        "diagnostics": diag,
    }


def _need_login(status: int, final_url: str) -> bool:
    return status in (401, 403) or (status in (301, 302, 303) and _looks_like_login(final_url))


# ===================== 结构化提取 =====================

def _extract_structured(html: str, base_url: str, include_tables: bool, include_links: bool,
                        include_images: bool) -> dict:
    """优先用 BeautifulSoup 提取结构化信息，缺失时降级为正则"""
    out = {
        "title": _extract_title(html),
        "description": "",
        "keywords": "",
        "headings": [],
        "links": [],
        "tables": [],
        "images": [],
    }
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        if include_links:
            out["links"] = _extract_links_internal(html, base_url)[:200]
        return out

    soup = BeautifulSoup(html, "html.parser")

    meta_desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta_desc and meta_desc.get("content"):
        out["description"] = _clean_text(meta_desc["content"])
    meta_kw = soup.find("meta", attrs={"name": re.compile("^keywords$", re.I)})
    if meta_kw and meta_kw.get("content"):
        out["keywords"] = _clean_text(meta_kw["content"])

    for tag in soup.find_all(re.compile("^h[1-6]$", re.I))[:80]:
        txt = _clean_text(tag.get_text())
        if txt:
            out["headings"].append({"level": int(tag.name[1]), "text": txt})

    if include_links:
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(base_url, href) if base_url else href
            links.append({"text": _clean_text(a.get_text())[:100], "href": full})
        out["links"] = links[:300]

    if include_images:
        images = []
        for img in soup.find_all("img", src=True):
            images.append({
                "src": urljoin(base_url, img["src"]) if base_url else img["src"],
                "alt": _clean_text(img.get("alt", "")),
            })
        out["images"] = images[:100]

    if include_tables:
        for table in soup.find_all("table")[:10]:
            rows = []
            for tr in table.find_all("tr")[:50]:
                cells = [_clean_text(td.get_text()) for td in tr.find_all(["th", "td"])]
                if any(cells):
                    rows.append(cells)
            if rows:
                out["tables"].append(rows)

    return out


# ===================== 注册函数 =====================

def register_spider_tools(mcp, base_dir: str = ""):
    """注册网页爬虫工具到 MCP 服务器"""
    if not base_dir:
        base_dir = os.environ.get("MCP_DATA_DIR", "/data/mcp-user-data")

    # ---------------- web_fetch ----------------
    @mcp.tool(
        name="web_fetch",
        description=(
            "智能抓取单个网页并提取正文。默认先做静态抓取（快），若检测到空壳/SPA/需启用 JS 的页面，"
            "且服务已启用渲染，会自动升级为无头浏览器重新抓取。返回 JSON 诊断信息："
            "http_status/final_url/render_used/reachable/need_login/is_spa/title/content_length/"
            "truncated/extracted_text/links。"
            "Args: url(网页地址,必填), render(auto|never|always,默认auto), timeout(秒,默认20), "
            "max_chars(正文最大字符数,默认60000), state(登录态名称,可选), wait_selector(等待元素,可选), "
            "include_links(是否返回页面链接,默认True)"
        ),
    )
    async def web_fetch(
        url: str,
        render: str = "auto",
        timeout: int = 20,
        max_chars: int = 0,
        state: str = "",
        wait_selector: str = "",
        include_links: bool = True,
    ) -> str:
        if not _is_intranet_url(url):
            return _err("BLOCKED", f"目标地址不在允许的访问范围内: {url}")
        host = urlparse(url).hostname or ""
        if not _check_rate_limit(host):
            return _err("RATE_LIMITED", f"请求过于频繁，请稍后再试: {host}")

        r = await _smart_fetch(url, render=render, timeout=timeout,
                               state_name=state, base_dir=base_dir, wait_selector=wait_selector)
        limit = max_chars or _DEFAULT_MAX_CHARS
        text = r["text"]
        payload = {
            "status": "ok" if r["html"] else "error",
            "url": url,
            "final_url": r["final_url"],
            "http_status": r["status"],
            "render_used": r["render_used"],
            "reachable": bool(r["html"]),
            "need_login": _need_login(r["status"], r["final_url"]),
            "is_spa": r["is_spa"],
            "encoding": r["encoding"],
            "title": r["title"],
            "content_length": len(text),
            "truncated": len(text) > limit,
            "extracted_text": text[:limit],
        }
        if include_links:
            payload["links"] = _extract_links_internal(r["html"], r["final_url"])[:200] if r["html"] else []
        if r["diagnostics"]:
            payload["diagnostics"] = r["diagnostics"]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ---------------- web_crawl ----------------
    @mcp.tool(
        name="web_crawl",
        description=(
            "并发递归爬取站点并提取每页正文（默认仅同域名链接）。返回 JSON 汇总，每页包含 "
            "url/depth/http_status/title/content_length/render_used/preview 与完整正文（受 max_chars_per_page 限制）。"
            "可选 save_markdown=True 将全部页面落盘为 Markdown 文件并返回路径。"
            "Args: url(起始URL,必填), max_depth(最大深度,默认3), max_pages(最大页数,默认50), "
            "concurrency(并发数,默认5), render(auto|never|always,默认auto), same_host(仅同域名,默认True), "
            "max_chars_per_page(每页正文上限,默认20000), save_markdown(是否落盘,默认False), "
            "state(登录态名称,可选), timeout(单页超时秒,默认20)"
        ),
    )
    async def web_crawl(
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        concurrency: int = 5,
        render: str = "auto",
        same_host: bool = True,
        max_chars_per_page: int = 20000,
        save_markdown: bool = False,
        state: str = "",
        timeout: int = 20,
    ) -> str:
        if not _is_intranet_url(url):
            return _err("BLOCKED", f"目标地址不在允许的访问范围内: {url}")

        start_host = urlparse(url).hostname or ""
        sem = asyncio.Semaphore(max(1, concurrency))
        visited = {url}
        pages = []
        current = [(url, 0)]
        save_md = save_markdown

        async def fetch_one(u: str, depth: int):
            async with sem:
                host = urlparse(u).hostname or ""
                if not _check_rate_limit(host):
                    await asyncio.sleep(1.0)
                return depth, u, await _smart_fetch(
                    u, render=render, timeout=timeout, state_name=state, base_dir=base_dir
                )

        while current and len(pages) < max_pages:
            batch = current[: max_pages - len(pages)]
            current = []
            results = await asyncio.gather(*[fetch_one(u, d) for (u, d) in batch], return_exceptions=True)

            for item in results:
                if isinstance(item, Exception):
                    pages.append({"url": "?", "depth": -1, "http_status": 0, "title": "",
                                  "content_length": 0, "render_used": "none", "error": str(item)})
                    continue
                depth, u, r = item
                text = r["text"]
                pages.append({
                    "url": u,
                    "depth": depth,
                    "final_url": r["final_url"],
                    "http_status": r["status"],
                    "title": r["title"],
                    "content_length": len(text),
                    "render_used": r["render_used"],
                    "truncated": len(text) > max_chars_per_page,
                    "content": text[:max_chars_per_page],
                })
                if depth < max_depth and len(visited) < max_pages:
                    for link in _extract_links_internal(r["html"], r["final_url"]):
                        if link in visited or not _is_intranet_url(link):
                            continue
                        if same_host and urlparse(link).hostname != start_host:
                            continue
                        visited.add(link)
                        current.append((link, depth + 1))

        payload = {
            "status": "ok",
            "start_url": url,
            "page_count": len(pages),
            "max_depth": max_depth,
            "pages": pages,
        }

        if save_md:
            try:
                out_dir = Path(base_dir) / "crawl_output"
                out_dir.mkdir(parents=True, exist_ok=True)
                fname = f"crawl_{int(time.time())}.md"
                fpath = out_dir / fname
                lines = [f"# 爬取结果: {url}", ""]
                for p in pages:
                    lines.append(f"## [{p['depth']}] {p['title'] or p['url']}")
                    lines.append(f"- URL: {p['url']}")
                    lines.append(f"- 状态: {p.get('http_status')} / 渲染: {p.get('render_used')}")
                    lines.append("")
                    lines.append(p.get("content", ""))
                    lines.append("")
                fpath.write_text("\n".join(lines), encoding="utf-8")
                payload["markdown_path"] = str(fpath)
            except Exception as e:
                payload["markdown_error"] = str(e)

        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ---------------- web_render_fetch ----------------
    @mcp.tool(
        name="web_render_fetch",
        description=(
            "强制使用无头浏览器(Chromium)渲染抓取页面，适用于 SPA / JS 动态渲染 / 需等待接口返回的页面。"
            "返回 JSON：http_status/final_url/title/content_length/extracted_text（可选 screenshot_base64）。"
            "Args: url(网页地址,必填), wait_until(load|domcontentloaded|networkidle,默认domcontentloaded), "
            "wait_selector(等待出现的元素选择器,可选), timeout(秒,默认30), max_chars(正文最大字符数,默认60000), "
            "screenshot(是否返回整页截图Base64,默认False), state(登录态名称,可选)"
        ),
    )
    async def web_render_fetch(
        url: str,
        wait_until: str = "domcontentloaded",
        wait_selector: str = "",
        timeout: int = 30,
        max_chars: int = 0,
        screenshot: bool = False,
        state: str = "",
    ) -> str:
        if not _is_intranet_url(url):
            return _err("BLOCKED", f"目标地址不在允许的访问范围内: {url}")
        host = urlparse(url).hostname or ""
        if not _check_rate_limit(host):
            return _err("RATE_LIMITED", f"请求过于频繁，请稍后再试: {host}")

        st = _load_state(base_dir, state)
        rendered = await _render_page(
            url, timeout=timeout, wait_until=wait_until,
            wait_selector=wait_selector, state=st, screenshot=screenshot,
        )
        if not rendered.get("ok"):
            return _err(rendered.get("error", "RENDER_ERROR"), rendered.get("message", "渲染失败"))

        html = rendered["html"]
        text = _extract_main_content(html)
        limit = max_chars or _DEFAULT_MAX_CHARS
        payload = {
            "status": "ok",
            "url": url,
            "final_url": rendered.get("final_url", url),
            "http_status": rendered.get("status", 0),
            "render_used": "chromium",
            "title": rendered.get("title", "") or _extract_title(html),
            "content_length": len(text),
            "truncated": len(text) > limit,
            "extracted_text": text[:limit],
        }
        if rendered.get("screenshot_base64"):
            payload["screenshot_base64"] = rendered["screenshot_base64"]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ---------------- web_extract ----------------
    @mcp.tool(
        name="web_extract",
        description=(
            "从 URL 或 HTML 源码中结构化提取信息：标题、meta 描述/关键词、标题层级(h1-h6)、正文、链接、表格、图片。"
            "当 source 以 http(s):// 开头时按 URL 抓取（必要时自动渲染），否则按 HTML 源码处理。"
            "Args: source(URL或HTML内容,必填), base_url(解析相对链接的基础URL,可选), "
            "include_tables(是否提取表格,默认True), include_links(是否提取链接,默认True), "
            "include_images(是否提取图片,默认False), max_chars(正文上限,默认60000), render(auto|never|always,默认auto)"
        ),
    )
    async def web_extract(
        source: str,
        base_url: str = "",
        include_tables: bool = True,
        include_links: bool = True,
        include_images: bool = False,
        max_chars: int = 0,
        render: str = "auto",
    ) -> str:
        html = ""
        final_url = base_url
        render_used = "none"
        diag = {}

        if source.strip().lower().startswith(("http://", "https://")):
            if not _is_intranet_url(source):
                return _err("BLOCKED", f"目标地址不在允许的访问范围内: {source}")
            host = urlparse(source).hostname or ""
            if not _check_rate_limit(host):
                return _err("RATE_LIMITED", f"请求过于频繁，请稍后再试: {host}")
            r = await _smart_fetch(source, render=render, timeout=20, base_dir=base_dir)
            html = r["html"]
            final_url = r["final_url"] or source
            render_used = r["render_used"]
            diag = r["diagnostics"]
            if not html:
                return _err("FETCH_ERROR", f"抓取失败: {source}")
        else:
            html = source
            if not final_url:
                m = re.search(r'<base[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE)
                if m:
                    final_url = m.group(1)

        extracted = _extract_structured(html, final_url, include_tables, include_links, include_images)
        text = _extract_main_content(html)
        limit = max_chars or _DEFAULT_MAX_CHARS

        payload = {
            "status": "ok",
            "url": final_url,
            "render_used": render_used,
            "title": extracted["title"],
            "description": extracted["description"],
            "keywords": extracted["keywords"],
            "headings": extracted["headings"],
            "content_length": len(text),
            "truncated": len(text) > limit,
            "main_text": text[:limit],
        }
        if include_links:
            payload["links"] = extracted["links"]
        if include_images:
            payload["images"] = extracted["images"]
        if include_tables and extracted["tables"]:
            payload["tables"] = extracted["tables"]
        if diag:
            payload["diagnostics"] = diag
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ---------------- web_login_state ----------------
    @mcp.tool(
        name="web_login_state",
        description=(
            "管理抓取用的登录态（cookies / 自定义请求头），保存后可在 web_fetch / web_crawl / "
            "web_render_fetch / web_extract 中通过 state=<name> 引用，用于需要登录或跨域鉴权的页面。"
            "action: save(保存,需 name 且 cookies/headers 至少一个) | list(列出全部) | "
            "show(查看,值脱敏) | delete(删除)。"
            "Args: action(默认list), name(登录态名称), cookies(JSON,支持数组或键值对象), headers(JSON对象), url(关联地址,可选)"
        ),
    )
    def web_login_state(
        action: str = "list",
        name: str = "",
        cookies: str = "",
        headers: str = "",
        url: str = "",
    ) -> str:
        state_dir = Path(base_dir) / "browser_state"

        if action == "list":
            if not state_dir.exists():
                return json.dumps({"status": "ok", "states": []}, ensure_ascii=False)
            items = []
            for f in sorted(state_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                items.append({
                    "name": f.stem,
                    "url": data.get("url", ""),
                    "cookie_count": len(data.get("cookies", [])),
                    "header_count": len(data.get("headers", {})),
                    "saved_at": data.get("saved_at", ""),
                })
            return json.dumps({"status": "ok", "states": items}, ensure_ascii=False, indent=2)

        if not name:
            return _err("BAD_ARGS", "请提供 name")

        path = _state_path(base_dir, name)

        if action == "save":
            parsed_headers = {}
            if headers:
                try:
                    parsed_headers = json.loads(headers) if isinstance(headers, str) else dict(headers)
                except Exception:
                    return _err("BAD_HEADERS", "headers 不是合法 JSON 对象")
            norm_cookies = _normalize_cookies(cookies)
            if not norm_cookies and not parsed_headers:
                return _err("EMPTY", "cookies 与 headers 至少提供一个")

            data = {
                "name": name,
                "url": url,
                "headers": parsed_headers,
                "cookies": norm_cookies,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return json.dumps({
                "status": "ok",
                "message": f"登录态已保存: {name}",
                "cookie_count": len(norm_cookies),
                "header_count": len(parsed_headers),
                "path": str(path),
            }, ensure_ascii=False, indent=2)

        if action == "show":
            data = _load_state(base_dir, name)
            if not data:
                return _err("NOT_FOUND", f"登录态不存在: {name}")
            masked = []
            for c in data.get("cookies", []):
                v = c.get("value", "")
                masked.append({**c, "value": (v[:4] + "***") if len(v) > 4 else "***"})
            masked_headers = {}
            for k, v in (data.get("headers") or {}).items():
                v = str(v)
                masked_headers[k] = (v[:8] + "***") if len(v) > 8 else "***"
            return json.dumps({
                "status": "ok",
                "name": name,
                "url": data.get("url", ""),
                "saved_at": data.get("saved_at", ""),
                "cookies": masked,
                "headers": masked_headers,
            }, ensure_ascii=False, indent=2)

        if action == "delete":
            if path.exists():
                path.unlink()
                return json.dumps({"status": "ok", "message": f"已删除登录态: {name}"}, ensure_ascii=False)
            return _err("NOT_FOUND", f"登录态不存在: {name}")

        return _err("BAD_ACTION", f"不支持的操作: {action}（可用: save/list/show/delete）")

    logger.info("网页爬虫工具已注册（渲染: %s）", "开启" if _render_enabled() else "关闭")
