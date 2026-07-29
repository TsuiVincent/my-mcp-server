"""
mcp-browser-playwright - 浏览器自动化 MCP Server

基于 Playwright 的内网浏览器自动化。
支持页面导航、元素交互、截图、JS 执行。
"""
from mcp.server.fastmcp import FastMCP
import json
import base64
import sys
import asyncio
import re

# 创建服务器
mcp = FastMCP("mcp-browser-playwright", host="0.0.0.0", port=8008, json_response=True)

# =====================================================================
# 浏览器实例管理
# =====================================================================
_browser = None
_context = None
_page = None


async def _ensure_browser():
    """确保浏览器已启动（懒启动）"""
    global _browser, _context, _page
    if _browser is None or not _browser.is_connected():
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=True)
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
    if _page is None or _page.is_closed():
        _page = await _context.new_page()
    return _page


async def _snapshot(page) -> str:
    """生成页面无障碍快照（结构化元素树+唯一ref）"""
    # 为所有可交互元素注入 ref 属性
    await page.evaluate("""
    () => {
      let counter = 0;
      const interactive = 'a,button,input,select,textarea,[role=button],[role=link],[role=textbox],[role=combobox],[role=checkbox],[role=radio],[onclick]';
      document.querySelectorAll(interactive).forEach(el => {
        if (!el.hasAttribute('data-ref')) {
          el.setAttribute('data-ref', 'e' + (counter++));
        }
      });
    }
    """)

    # 生成 ARIA 快照
    try:
        snapshot = await page.accessibility.snapshot(interesting_only=False)
        if snapshot is None:
            return "(页面为空或尚未加载完成)"

        lines = []
        _build_snapshot_tree(snapshot, lines, depth=0)
        return "\n".join(lines)
    except Exception as e:
        # 降级：返回纯文本 + 元素列表
        try:
            text = await page.text_content("body") or ""
            text = text[:3000]
            return f"(快照不可用) 页面文本:\n{text}"
        except Exception:
            return f"(快照生成失败: {e})"


def _build_snapshot_tree(node: dict, lines: list, depth: int = 0) -> None:
    """递归构建无障碍树"""
    indent = "  " * depth
    role = node.get("role", "unknown")
    name = node.get("name", "")
    value = node.get("value", "")
    ref = ""

    # 尝试从 DOM 获取 ref
    nid = node.get("nodeId")

    if name:
        display = f"{role} \"{name}\""
    else:
        display = role

    if value:
        display += f" = \"{value}\""

    if ref:
        display = f"[{ref}] {display}"

    lines.append(f"{indent}- {display}")

    for child in node.get("children", []):
        _build_snapshot_tree(child, lines, depth + 1)


async def _find_element(ref: str):
    """根据 data-ref 属性定位元素"""
    page = await _ensure_browser()
    if ref.startswith("e"):
        el = await page.query_selector(f"[data-ref='{ref}']")
    else:
        el = await page.query_selector(ref)
    if el is None:
        raise ValueError(f"未找到元素: {ref}（可能页面已刷新，建议先获取 snapshot）")
    return el


def _make_error(code: str, msg: str) -> str:
    return json.dumps({"status": "error", "code": code, "message": msg}, ensure_ascii=False)


# =====================================================================
# 页面导航
# =====================================================================
@mcp.tool()
async def browser_navigate(url: str) -> str:
    """导航到指定URL，返回页面快照。

    Args:
        url: 目标URL（支持内网地址）
    """
    try:
        page = await _ensure_browser()
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        snapshot = await _snapshot(page)
        return json.dumps({
            "status": "ok",
            "url": page.url,
            "title": await page.title(),
            "snapshot": snapshot,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _make_error("NAVIGATE_ERROR", str(e))


@mcp.tool()
async def browser_snapshot() -> str:
    """获取当前页面的无障碍结构快照。返回结构化元素树，每个可交互元素有唯一 ref。"""
    try:
        page = await _ensure_browser()
        snapshot = await _snapshot(page)
        return json.dumps({
            "status": "ok",
            "url": page.url,
            "title": await page.title(),
            "snapshot": snapshot,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _make_error("SNAPSHOT_ERROR", str(e))


@mcp.tool()
async def browser_screenshot(full_page: bool = False) -> str:
    """对当前页面截图，返回 Base64 编码的 PNG。

    Args:
        full_page: 是否截取整页（默认仅视口）
    """
    try:
        page = await _ensure_browser()
        data = await page.screenshot(full_page=full_page, type="png")
        b64 = base64.b64encode(data).decode("ascii")
        return json.dumps({
            "status": "ok",
            "format": "png",
            "base64": b64,
            "url": page.url,
        }, ensure_ascii=False)
    except Exception as e:
        return _make_error("SCREENSHOT_ERROR", str(e))


@mcp.tool()
async def browser_go_back() -> str:
    """浏览器后退一页。"""
    try:
        page = await _ensure_browser()
        await page.go_back()
        return json.dumps({"status": "ok", "url": page.url}, ensure_ascii=False)
    except Exception as e:
        return _make_error("BACK_ERROR", str(e))


@mcp.tool()
async def browser_go_forward() -> str:
    """浏览器前进一页。"""
    try:
        page = await _ensure_browser()
        await page.go_forward()
        return json.dumps({"status": "ok", "url": page.url}, ensure_ascii=False)
    except Exception as e:
        return _make_error("FORWARD_ERROR", str(e))


# =====================================================================
# 元素交互
# =====================================================================
@mcp.tool()
async def browser_click(ref: str) -> str:
    """点击页面元素。

    Args:
        ref: 元素引用（来自 snapshot 的 ref 或 CSS selector）
    """
    try:
        el = await _find_element(ref)
        await el.click()
        page = await _ensure_browser()
        await asyncio.sleep(0.5)
        snapshot = await _snapshot(page)
        return json.dumps({
            "status": "ok",
            "clicked": ref,
            "url": page.url,
            "snapshot": snapshot,
        }, ensure_ascii=False, indent=2)
    except ValueError as ve:
        return _make_error("ELEMENT_NOT_FOUND", str(ve))
    except Exception as e:
        return _make_error("CLICK_ERROR", str(e))


@mcp.tool()
async def browser_type(ref: str, text: str) -> str:
    """在输入框中逐字符输入文本（触发 input 事件）。

    Args:
        ref: 元素引用
        text: 要输入的文本
    """
    try:
        el = await _find_element(ref)
        await el.click()
        await asyncio.sleep(0.1)
        await el.fill("")
        await el.type(text, delay=30)
        return json.dumps({"status": "ok", "typed": text, "ref": ref}, ensure_ascii=False)
    except ValueError as ve:
        return _make_error("ELEMENT_NOT_FOUND", str(ve))
    except Exception as e:
        return _make_error("TYPE_ERROR", str(e))


@mcp.tool()
async def browser_fill(ref: str, value: str) -> str:
    """快速填充表单输入框（直接设置 value）。

    Args:
        ref: 元素引用
        value: 要填充的值
    """
    try:
        el = await _find_element(ref)
        await el.fill(value)
        return json.dumps({"status": "ok", "filled": value, "ref": ref}, ensure_ascii=False)
    except ValueError as ve:
        return _make_error("ELEMENT_NOT_FOUND", str(ve))
    except Exception as e:
        return _make_error("FILL_ERROR", str(e))


@mcp.tool()
async def browser_select_option(ref: str, value: str) -> str:
    """在下拉框中选择选项。

    Args:
        ref: 元素引用
        value: 选项值（option 的 value 或文本内容）
    """
    try:
        el = await _find_element(ref)
        await el.select_option(value)
        return json.dumps({"status": "ok", "selected": value, "ref": ref}, ensure_ascii=False)
    except ValueError as ve:
        return _make_error("ELEMENT_NOT_FOUND", str(ve))
    except Exception as e:
        return _make_error("SELECT_ERROR", str(e))


@mcp.tool()
async def browser_hover(ref: str) -> str:
    """鼠标悬停在元素上（触发 hover 效果/下拉菜单）。

    Args:
        ref: 元素引用
    """
    try:
        el = await _find_element(ref)
        await el.hover()
        return json.dumps({"status": "ok", "hovered": ref}, ensure_ascii=False)
    except ValueError as ve:
        return _make_error("ELEMENT_NOT_FOUND", str(ve))
    except Exception as e:
        return _make_error("HOVER_ERROR", str(e))


@mcp.tool()
async def browser_press_key(key: str) -> str:
    """模拟键盘按键。

    Args:
        key: 按键名称（Enter, Tab, Escape, ArrowDown, ArrowUp, PageDown 等）
    """
    try:
        page = await _ensure_browser()
        await page.keyboard.press(key)
        return json.dumps({"status": "ok", "key": key}, ensure_ascii=False)
    except Exception as e:
        return _make_error("KEY_ERROR", str(e))


# =====================================================================
# 高级操作
# =====================================================================
@mcp.tool()
async def browser_evaluate(expression: str) -> str:
    """在页面上执行 JavaScript 表达式并返回结果。

    Args:
        expression: JavaScript 表达式，如 "document.title" 或 "JSON.stringify({links: [...document.querySelectorAll('a')].map(a => a.href)})"
    """
    try:
        page = await _ensure_browser()
        result = await page.evaluate(expression)
        return json.dumps({
            "status": "ok",
            "result": result,
        }, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return _make_error("EVALUATE_ERROR", str(e))


@mcp.tool()
async def browser_get_page_text() -> str:
    """获取当前页面的纯文本内容（去除 HTML 标签）。"""
    try:
        page = await _ensure_browser()
        text = await page.text_content("body") or ""
        return json.dumps({
            "status": "ok",
            "url": page.url,
            "text": text[:10000],
            "truncated": len(text) > 10000,
        }, ensure_ascii=False)
    except Exception as e:
        return _make_error("TEXT_ERROR", str(e))


@mcp.tool()
async def browser_close() -> str:
    """关闭当前页面（释放内存）。"""
    global _page
    try:
        if _page and not _page.is_closed():
            await _page.close()
        _page = None
        return json.dumps({"status": "ok", "message": "页面已关闭"}, ensure_ascii=False)
    except Exception as e:
        return _make_error("CLOSE_ERROR", str(e))


print("[MCP Server] mcp-browser-playwright 已就绪，端口: 8008", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
