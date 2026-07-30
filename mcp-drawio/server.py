"""
mcp-drawio - Draw.io 图表生成与预览 MCP Server

基于 draw.io 的 AI 图表生成服务，支持：
- 创建/编辑 draw.io XML 图表
- 浏览器实时预览
- 导出为 .drawio / .png / .svg 文件

端口: 19110
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

# ── 路径配置 ──────────────────────────────────────────────
HERE = Path(__file__).resolve().parent

# ── 日志 ──────────────────────────────────────────────────
import logging
logging.basicConfig(level=logging.INFO, format='[DrawIO-MCP] %(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('mcp-drawio')

# ── 创建 MCP 服务器 ───────────────────────────────────────
mcp = FastMCP("mcp-drawio", host="0.0.0.0", port=19110, json_response=True)

# ── 工作目录 ──────────────────────────────────────────────
if sys.platform == "win32":
    base_dir = os.path.join(os.path.expanduser("~"), "mcp-data", "drawio")
else:
    base_dir = "/data/drawio"
os.makedirs(base_dir, exist_ok=True)

# ── 会话存储 ──────────────────────────────────────────────
_sessions: dict[str, dict] = {}
_sessions_lock = threading.RLock()  # 可重入锁：允许同一线程多次获取
SESSION_TTL_SECONDS = 3600  # 1 小时过期

_last_cleanup_time = 0.0


def _cleanup_expired_sessions():
    """清理过期会话（最多每5分钟执行一次）"""
    global _last_cleanup_time
    now = time.time()
    if now - _last_cleanup_time < 300:  # 5分钟内不再执行
        return
    _last_cleanup_time = now

    cutoff = datetime.now() - timedelta(seconds=SESSION_TTL_SECONDS)
    with _sessions_lock:
        expired = [
            sid for sid, s in _sessions.items()
            if datetime.fromisoformat(s["updated_at"]) < cutoff
        ]
        for sid in expired:
            del _sessions[sid]
        if expired:
            logger.info(f"Cleaned {len(expired)} expired sessions, {len(_sessions)} remaining")

# draw.io 默认模板
BLANK_DIAGRAM = """<mxfile host="app.diagrams.net" modified="2026-01-01T00:00:00.000Z" agent="mcp-drawio" version="21.0.0" type="device">
  <diagram name="Page-1" id="page1">
    <mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""


def _get_session(session_id: str) -> dict:
    """获取或创建会话"""
    _cleanup_expired_sessions()
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = {
                "id": session_id,
                "diagram_xml": BLANK_DIAGRAM,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "page_count": 1,
            }
        return _sessions[session_id]


def _update_session_xml(session_id: str, xml: str):
    """更新会话的 XML"""
    with _sessions_lock:
        s = _get_session(session_id)
        s["diagram_xml"] = xml
        s["updated_at"] = datetime.now().isoformat()
        # 统计页数
        page_count = len(re.findall(r'<diagram\s', xml))
        s["page_count"] = max(page_count, 1)


def _resolve_safe_path(filename: str) -> str:
    """安全路径解析"""
    # 清理文件名
    safe_name = os.path.basename(filename)
    if not safe_name:
        safe_name = "diagram.drawio"
    target = os.path.join(base_dir, safe_name)
    os.makedirs(base_dir, exist_ok=True)
    return target


# ═══════════════════════════════════════════════════════════
# 内嵌 HTTP 预览服务 (Starlette)
# ═══════════════════════════════════════════════════════════

PREVIEW_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Draw.io Preview - {session_id}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ overflow: hidden; background: #f0f0f0; }}
  #embed-container {{ width: 100vw; height: 100vh; }}
  iframe {{ width: 100%; height: 100%; border: none; }}
  #status {{ position: fixed; bottom: 10px; right: 10px; padding: 6px 12px;
             background: rgba(0,0,0,0.7); color: #fff; border-radius: 4px;
             font: 12px monospace; z-index: 9999; }}
  .loading {{ position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%);
             font: 18px sans-serif; color: #666; }}
</style>
</head>
<body>
<div id="embed-container">
  <div class="loading">Loading draw.io...</div>
</div>
<div id="status">Ready</div>

<script>
const SESSION_ID = "{session_id}";
const DRAWIO_URL = "{drawio_base_url}";
const POLL_INTERVAL = 2000;

let iframe = null;
let lastXml = "";

function setStatus(msg) {{
  document.getElementById("status").textContent = msg;
}}

async function fetchDiagram() {{
  try {{
    const resp = await fetch("/api/diagram/" + SESSION_ID);
    const data = await resp.json();
    if (data.xml && data.xml !== lastXml) {{
      lastXml = data.xml;
      return data.xml;
    }}
  }} catch(e) {{
    console.error("Fetch error:", e);
  }}
  return null;
}}

async function saveDiagram(xml) {{
  try {{
    await fetch("/api/diagram/" + SESSION_ID, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ xml: xml }})
    }});
    lastXml = xml;
    setStatus("Saved " + new Date().toLocaleTimeString());
  }} catch(e) {{
    console.error("Save error:", e);
    setStatus("Save failed");
  }}
}}

function createEmbed(xml) {{
  const container = document.getElementById("embed-container");
  container.innerHTML = "";

  const iframeHtml = `<iframe src="${{DRAWIO_URL}}?embed=1&ui=atlas&spin=1&modified=unsaved&proto=json"
    id="drawio-iframe"></iframe>`;
  container.innerHTML = iframeHtml;
  iframe = document.getElementById("drawio-iframe");

  const receive = (evt) => {{
    if (!evt.data || typeof evt.data !== "string") return;
    let msg;
    try {{ msg = JSON.parse(evt.data); }} catch(e) {{ return; }}

    if (msg.event === "init") {{
      iframe.contentWindow.postMessage(JSON.stringify({{
        action: "load",
        autosave: 1,
        xml: xml
      }}), "*");
      setStatus("Loaded");
    }} else if (msg.event === "save") {{
      saveDiagram(msg.xml);
    }}
  }};
  window.addEventListener("message", receive);
}}

async function init() {{
  const xml = await fetchDiagram();
  if (xml) {{
    createEmbed(xml);
  }} else {{
    createEmbed(`{blank_diagram_escaped}`);
  }}

  // Poll for external changes
  setInterval(async () => {{
    const newXml = await fetchDiagram();
    if (newXml && iframe) {{
      iframe.contentWindow.postMessage(JSON.stringify({{
        action: "load",
        autosave: 1,
        xml: newXml
      }}), "*");
    }}
  }}, POLL_INTERVAL);
}}

init();
</script>
</body>
</html>"""

STARLETTE_APP = None


def _create_starlette_app():
    """创建 Starlette 应用用于预览"""
    drawio_base_url = os.environ.get("DRAWIO_BASE_URL", "https://embed.diagrams.net")

    # 转义用于 JS 模板字符串的 XML
    blank_escaped = BLANK_DIAGRAM.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

    async def preview_page(request):
        session_id = request.path_params.get("session_id", "demo")
        html = PREVIEW_HTML.format(
            session_id=session_id,
            drawio_base_url=drawio_base_url,
            blank_diagram_escaped=blank_escaped,
        )
        return HTMLResponse(html)

    async def api_get_diagram(request):
        session_id = request.path_params.get("session_id", "demo")
        s = _get_session(session_id)
        return JSONResponse({
            "xml": s["diagram_xml"],
            "updated_at": s["updated_at"],
        })

    async def api_save_diagram(request):
        session_id = request.path_params.get("session_id", "demo")
        try:
            body = await request.json()
            xml = body.get("xml", "")
            if xml:
                _update_session_xml(session_id, xml)
            return JSONResponse({"status": "ok"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def health(request):
        return JSONResponse({
            "status": "ok",
            "sessions": len(_sessions),
            "drawio_base_url": drawio_base_url,
        })

    routes = [
        Route("/preview/{session_id}", preview_page),
        Route("/api/diagram/{session_id}", api_get_diagram, methods=["GET"]),
        Route("/api/diagram/{session_id}", api_save_diagram, methods=["POST"]),
        Route("/health", health),
    ]

    return Starlette(routes=routes)


def _ensure_starlette():
    global STARLETTE_APP
    if STARLETTE_APP is None:
        STARLETTE_APP = _create_starlette_app()
    return STARLETTE_APP


# ── HTTP 服务器（独立线程）────────────────────────────────
_http_thread = None
_http_port = 19111


def _find_free_port(start: int, span: int = 50) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def _start_preview_server():
    """启动内嵌 HTTP 预览服务器"""
    import uvicorn

    global _http_port, _http_thread
    _http_port = int(os.environ.get("DRAWIO_PREVIEW_PORT", "0")) or _find_free_port(19111)

    app = _ensure_starlette()
    config = uvicorn.Config(app, host="0.0.0.0", port=_http_port, log_level="warning")
    server = uvicorn.Server(config)

    _http_thread = threading.Thread(target=server.run, daemon=True)
    _http_thread.start()
    time.sleep(0.5)  # 等待启动
    logger.info(f"Preview HTTP server started on port {_http_port}")


_start_preview_server()


# ═══════════════════════════════════════════════════════════
# MCP 工具定义
# ═══════════════════════════════════════════════════════════

@mcp.tool()
async def drawio_start_session() -> str:
    """创建新的绘图会话并返回浏览器预览 URL。

    必须先调用此工具创建会话，获得 session_id 和 preview_url。
    在浏览器中打开 preview_url 可实时查看图表变化。

    Returns:
        JSON: {"session_id": "...", "preview_url": "http://..."}
    """
    session_id = uuid.uuid4().hex[:12]
    s = _get_session(session_id)
    preview_base = os.environ.get("DRAWIO_PREVIEW_BASE", f"http://127.0.0.1:{_http_port}")
    preview_url = f"{preview_base}/preview/{session_id}"

    return json.dumps({
        "status": "ok",
        "session_id": session_id,
        "preview_url": preview_url,
        "hint": "在浏览器中打开 preview_url 可实时预览图表。创建图表后会自动刷新。",
    }, ensure_ascii=False)


@mcp.tool()
async def drawio_get_diagram(session_id: str) -> str:
    """获取当前会话的图表 XML 内容。

    Args:
        session_id: 会话ID，来自 drawio_start_session

    Returns:
        JSON: {"session_id": "...", "xml": "<mxfile>...", "page_count": N}
    """
    s = _get_session(session_id)
    return json.dumps({
        "session_id": session_id,
        "xml": s["diagram_xml"],
        "page_count": s["page_count"],
        "updated_at": s["updated_at"],
    }, ensure_ascii=False)


@mcp.tool()
async def drawio_create_diagram(session_id: str, xml: str) -> str:
    """用 draw.io XML 创建或替换当前会话的图表。

    此工具接收完整的 mxfile XML 字符串，直接设置到会话中。
    调用后浏览器预览会自动刷新。

    Args:
        session_id: 会话ID
        xml: draw.io mxfile XML 内容（完整格式）

    Returns:
        JSON: {"status": "ok", "page_count": N}
    """
    if not xml.strip().startswith("<mxfile"):
        return json.dumps({
            "error": "无效的 XML 格式",
            "hint": "XML 必须以 <mxfile> 为根元素，参考 draw.io mxfile 格式",
        }, ensure_ascii=False)

    _update_session_xml(session_id, xml)
    s = _get_session(session_id)
    preview_base = os.environ.get("DRAWIO_PREVIEW_BASE", f"http://127.0.0.1:{_http_port}")

    return json.dumps({
        "status": "ok",
        "session_id": session_id,
        "page_count": s["page_count"],
        "preview_url": f"{preview_base}/preview/{session_id}",
    }, ensure_ascii=False)


@mcp.tool()
async def drawio_export_diagram(
    session_id: str,
    output_filename: str = "diagram.drawio",
    format: str = "drawio",
) -> str:
    """导出当前会话的图表为文件。

    支持三种格式：
    - drawio: .drawio 文件（可用 draw.io / VS Code 插件打开编辑）
    - png: PNG 图片（通过 draw.io 在线服务导出）
    - svg: SVG 矢量图（通过 draw.io 在线服务导出）

    Args:
        session_id: 会话ID
        output_filename: 输出文件名
        format: 导出格式，"drawio" / "png" / "svg"

    Returns:
        JSON: {"status": "ok", "output_path": "...", "base64_content": "..."}
    """
    s = _get_session(session_id)
    xml = s["diagram_xml"]

    if format == "drawio":
        output = _resolve_safe_path(output_filename)
        with open(output, "w", encoding="utf-8") as f:
            f.write(xml)
        return json.dumps({
            "status": "ok",
            "format": "drawio",
            "output_path": output,
            "hint": "文件已保存。可用 draw.io 桌面版、VS Code Draw.io 插件、或 https://app.diagrams.net/ 打开编辑。",
        }, ensure_ascii=False)

    if format in ("png", "svg"):
        try:
            drawio_base = os.environ.get("DRAWIO_BASE_URL", "https://embed.diagrams.net")
            export_url = f"{drawio_base}/export"

            export_data = {
                "format": format,
                "xml": xml,
                "bg": "white",
                "scale": 2 if format == "png" else 1,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(export_url, data=export_data)
                if resp.status_code == 200:
                    output = _resolve_safe_path(output_filename)
                    with open(output, "wb") as f:
                        f.write(resp.content)
                    b64 = base64.b64encode(resp.content).decode("utf-8")
                    return json.dumps({
                        "status": "ok",
                        "format": format,
                        "output_path": output,
                        "base64_content": b64,
                        "hint": f"导出成功。base64_content 可直接传给 file_save_to_download(encoding='base64') 保存。",
                    }, ensure_ascii=False)
                else:
                    return json.dumps({
                        "error": f"导出失败: HTTP {resp.status_code}",
                        "hint": "draw.io 导出服务不可用，请尝试 format='drawio' 保存后用桌面版导出",
                    }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({
                "error": f"导出异常: {e}",
                "hint": "网络不通或 draw.io 服务不可用。可改用 format='drawio' 保存文件后用桌面版 draw.io 导出为图片",
            }, ensure_ascii=False)

    return json.dumps({"error": f"不支持的格式: {format}，请使用 drawio / png / svg"}, ensure_ascii=False)


@mcp.tool()
async def drawio_edit_diagram(
    session_id: str,
    operation: str,
    cell_id: str = "",
    attributes: str = "",
) -> str:
    """编辑当前图表中的单元格（cell）。

    支持三种操作：
    - update: 更新指定 cell 的属性（如位置、大小、颜色等）
    - add: 添加新的 cell 元素
    - delete: 删除指定 cell

    Args:
        session_id: 会话ID
        operation: 操作类型，"update" / "add" / "delete"
        cell_id: 目标 cell 的 id（update/delete 时必须）
        attributes: 属性字符串，如 'fillColor="#FF0000"' 或新 cell 的完整 XML（add 时）

    Returns:
        JSON: {"status": "ok", "operation": "update", "cell_id": "..."}
    """
    s = _get_session(session_id)
    xml = s["diagram_xml"]

    if operation == "delete":
        if not cell_id:
            return json.dumps({"error": "delete 操作需要 cell_id 参数"}, ensure_ascii=False)
        # 匹配自闭合 <mxCell .../> 或带子元素的 <mxCell ...>...</mxCell>
        pattern = (
            r'<mxCell\s[^>]*\bid="' + re.escape(cell_id) + r'"'
            r'(?:[^/>]*/>'                          # 自闭合: <mxCell id="x" .../>
            r'|>[^<]*(?:<(?!!mxCell\b)[^<]*)*</mxCell>)'  # 带子元素: <mxCell id="x">...<mxGeometry.../></mxCell>
        )
        new_xml = re.sub(pattern, "", xml, count=1, flags=re.DOTALL)
        if new_xml == xml:
            return json.dumps({"error": f"未找到 id='{cell_id}' 的 cell"}, ensure_ascii=False)
        _update_session_xml(session_id, new_xml)
        return json.dumps({"status": "ok", "operation": "delete", "cell_id": cell_id}, ensure_ascii=False)

    if operation == "update":
        if not cell_id or not attributes:
            return json.dumps({"error": "update 操作需要 cell_id 和 attributes"}, ensure_ascii=False)
        # 查找并更新 cell
        def _replace_attrs(match):
            cell_content = match.group(0)
            for attr_pair in attributes.replace(",", " ").split():
                if "=" in attr_pair:
                    key, _, value = attr_pair.partition("=")
                    value = value.strip("\"'")
                    key = key.strip()
                    # 替换或追加属性
                    if re.search(rf'\b{re.escape(key)}="[^"]*"', cell_content):
                        cell_content = re.sub(
                            rf'\b{re.escape(key)}="[^"]*"',
                            f'{key}="{value}"',
                            cell_content,
                        )
                    else:
                        # 在 /> 或 > 前插入
                        cell_content = cell_content.replace(">", f' {key}="{value}">', 1)
            return cell_content

        pattern = r'<mxCell\s[^>]*\bid="' + re.escape(cell_id) + r'"[^/>]*(?:/>|>.*?</mxCell>)'
        new_xml = re.sub(pattern, _replace_attrs, xml, count=1, flags=re.DOTALL)
        if new_xml == xml:
            return json.dumps({"error": f"未找到 id='{cell_id}' 的 cell"}, ensure_ascii=False)
        _update_session_xml(session_id, new_xml)
        return json.dumps({"status": "ok", "operation": "update", "cell_id": cell_id}, ensure_ascii=False)

    if operation == "add":
        if not attributes:
            return json.dumps({"error": "add 操作需要 attributes（新 cell 的 XML）"}, ensure_ascii=False)
        if not attributes.strip().startswith("<mxCell"):
            return json.dumps({
                "error": "attributes 必须是有效的 mxCell XML 元素",
                "example": '<mxCell id="new1" value="Hello" style="rounded=1;whiteSpace=wrap;" vertex="1" parent="1"><mxGeometry x="100" y="100" width="120" height="60" as="geometry"/></mxCell>',
            }, ensure_ascii=False)
        # 在 </root> 前插入
        insert_pos = xml.rfind("</root>")
        if insert_pos == -1:
            # 尝试在 </mxGraphModel> 前插入
            insert_pos = xml.rfind("</mxGraphModel>")
        if insert_pos == -1:
            return json.dumps({"error": "无法在 XML 中找到插入位置"}, ensure_ascii=False)
        new_xml = xml[:insert_pos] + "\n        " + attributes.strip() + "\n      " + xml[insert_pos:]
        _update_session_xml(session_id, new_xml)
        return json.dumps({"status": "ok", "operation": "add", "cell_id": cell_id or "new"}, ensure_ascii=False)

    return json.dumps({"error": f"不支持的 operation: {operation}，请使用 update / add / delete"}, ensure_ascii=False)


@mcp.tool()
async def drawio_list_formats() -> str:
    """列出 draw.io XML 格式参考，包括常用 shape style 和 mxCell 属性。
    在创建图表前调用此工具了解支持的形状和样式。

    Returns:
        JSON: 格式参考文档
    """
    return json.dumps({
        "canvas": {
            "description": "默认画布 827x1169 (A4)。每个 mxCell 用 mxGeometry 放置",
            "pageWidth": 827,
            "pageHeight": 1169,
        },
        "core_cell_attributes": {
            "id": "唯一标识，如 '2', 'cell_3'",
            "value": "显示的文本",
            "style": "样式字符串（分号分隔）",
            "vertex": "1=形状（矩形/菱形等），0=连线",
            "edge": "1=连线",
            "parent": "父 cell id，通常根节点为 '1'",
            "source": "连线起点 cell id",
            "target": "连线终点 cell id",
        },
        "common_styles": {
            "rectangle": "rounded=0;whiteSpace=wrap;html=1;",
            "rounded_rect": "rounded=1;whiteSpace=wrap;html=1;",
            "ellipse": "ellipse;whiteSpace=wrap;html=1;",
            "diamond": "rhombus;whiteSpace=wrap;html=1;",
            "text": "text;html=1;align=center;",
            "arrow": "endArrow=classic;html=1;",
            "dashed_arrow": "dashed=1;endArrow=classic;html=1;",
            "cloud": "ellipse;shape=cloud;whiteSpace=wrap;html=1;",
            "cylinder": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=15;",
            "actor": "shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;",
        },
        "color_styles": {
            "fillColor": "#DAE8FC (填充色)",
            "strokeColor": "#6C8EBF (边框色)",
            "fontColor": "#333333 (文字色)",
        },
        "geometry_example": {
            "vertex": '<mxCell id="2" value="Hello" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">\n  <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>\n</mxCell>',
            "edge": '<mxCell id="3" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="4">\n  <mxGeometry relative="1" as="geometry"/>\n</mxCell>',
        },
        "layout_formats": {
            "horizontal_tree": "同层级水平排列",
            "vertical_flow": "从上到下流式布局",
            "grid_layout": "网格布局",
        },
    }, ensure_ascii=False)


@mcp.tool()
async def drawio_list_pages(session_id: str) -> str:
    """列出当前图表的所有页面（tabs）。

    Args:
        session_id: 会话ID

    Returns:
        JSON: {"pages": [{"id": "...", "name": "...", "index": N}]}
    """
    s = _get_session(session_id)
    xml = s["diagram_xml"]
    pages = []
    for m in re.finditer(r'<diagram\s[^>]*\bid="([^"]*)"[^>]*\bname="([^"]*)"', xml):
        pages.append({"id": m.group(1), "name": m.group(2), "index": len(pages)})

    return json.dumps({
        "session_id": session_id,
        "pages": pages,
        "page_count": len(pages),
    }, ensure_ascii=False)


@mcp.tool()
async def drawio_add_page(
    session_id: str,
    page_name: str = "Page-2",
) -> str:
    """向当前图表追加新页面。

    Args:
        session_id: 会话ID
        page_name: 新页面名称

    Returns:
        JSON: {"status": "ok", "page_id": "...", "page_count": N}
    """
    s = _get_session(session_id)
    xml = s["diagram_xml"]
    page_id = f"page-{uuid.uuid4().hex[:8]}"
    new_page = f"""  <diagram name="{page_name}" id="{page_id}">
    <mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
      </root>
    </mxGraphModel>
  </diagram>"""

    insert_pos = xml.rfind("</mxfile>")
    if insert_pos == -1:
        return json.dumps({"error": "无效的 mxfile 格式"}, ensure_ascii=False)
    new_xml = xml[:insert_pos] + "\n" + new_page + "\n" + xml[insert_pos:]
    _update_session_xml(session_id, new_xml)
    return json.dumps({
        "status": "ok",
        "page_id": page_id,
        "page_name": page_name,
        "page_count": _get_session(session_id)["page_count"],
    }, ensure_ascii=False)


print(f"[MCP Server] mcp-drawio 已就绪，端口: 19110", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
