#!/usr/bin/env python3
"""
PPT Master MCP Server
=====================
将 ppt-master 的PPT生成能力封装为 MCP (Model Context Protocol) 工具。
支持 SkillHub 平台通过 MCP 协议调用。

功能:
  - workspace 管理 (创建/文件读写/文件列表)
  - 源文档解析 (PDF/DOCX/MD/TXT/URL)
  - 模板浏览 (Layouts + Decks + Charts)
  - SVG 转 PPTX 导出
  - Live Preview (内置HTTP snippet server)

启动:
  python server.py --port 8011
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import base64

# ── 路径配置 ──────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
PPT_MASTER_DIR = HERE / 'ppt-master-main'
PPT_SKILL_DIR = PPT_MASTER_DIR / 'skills' / 'ppt-master'
PPT_SCRIPTS_DIR = PPT_SKILL_DIR / 'scripts'
PPT_TEMPLATES_DIR = PPT_SKILL_DIR / 'templates'

# 将 ppt-master scripts 加入 sys.path
if str(PPT_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(PPT_SCRIPTS_DIR))

# ── 工作区目录 ────────────────────────────────────────────
WORKSPACES_DIR = HERE / 'workspaces'
PREVIEW_PORT_START = 18111
_preview_server_instance: Optional['PreviewServer'] = None
_preview_lock = threading.Lock()

# ── 日志 ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='[PPT-MCP] %(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('ppt-master-mcp')

# ── FastMCP 检测 ──────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    logger.warning("FastMCP not installed. Install with: pip install mcp")

# ── 加载 .env 文件 ────────────────────────────────────────
def _load_dotenv(env_path: Path = None):
    """简易 .env 加载器，无需 python-dotenv 依赖。进程环境变量优先级更高。"""
    if env_path is None:
        env_path = HERE / '.env'
    if not env_path.exists():
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # 进程环境变量优先，不覆盖
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

# AI 图像生成开关（默认关闭）
PPT_IMAGE_GEN_ENABLED = os.environ.get('PPT_IMAGE_GEN_ENABLED', 'false').lower() == 'true'

# ============================================================
# 辅助函数
# ============================================================

def _ensure_workspaces():
    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)


def _get_workspace(project_id: str) -> Path:
    _ensure_workspaces()
    ws = WORKSPACES_DIR / project_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _find_free_port(start: int, span: int = 50) -> int:
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start


def _run_python_script(script_rel_path: str, *args, cwd: str = None, timeout: int = 120) -> dict:
    """运行 ppt-master-main 下的 Python 脚本。"""
    script_path = PPT_SCRIPTS_DIR / script_rel_path
    if not script_path.exists():
        return {'success': False, 'error': f'脚本不存在: {script_path}'}

    cmd = [sys.executable, str(script_path)] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or str(PPT_MASTER_DIR),
            env={**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [str(PPT_SCRIPTS_DIR), os.environ.get('PYTHONPATH', '')]))},
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout[-8000:] if len(result.stdout) > 8000 else result.stdout,
            'stderr': result.stderr[-3000:] if len(result.stderr) > 3000 else result.stderr,
            'returncode': result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': f'脚本超时 ({timeout}s)'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def _list_layout_templates() -> list[dict]:
    """列出可用布局模板（不含 design_spec 内容，需要时单独获取）。"""
    layouts_dir = PPT_TEMPLATES_DIR / 'layouts'
    index_path = layouts_dir / 'layouts_index.json'
    templates = []

    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
        for name, info in index.items():
            templates.append({
                'id': name,
                'type': 'layout',
                'name': name,
                'summary': info.get('summary', ''),
                'canvas_format': info.get('canvas_format', 'ppt169'),
                'page_count': info.get('page_count', 5),
                'page_types': info.get('page_types', []),
                'primary_color': info.get('primary_color', ''),
            })
    return templates


def _list_deck_templates() -> list[dict]:
    """列出可用整包模板（不含 design_spec 内容，需要时单独获取）。"""
    decks_dir = PPT_TEMPLATES_DIR / 'decks'
    index_path = decks_dir / 'decks_index.json'
    templates = []

    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
        for name, info in index.items():
            templates.append({
                'id': name,
                'type': 'deck',
                'name': name,
                'summary': info.get('summary', ''),
                'canvas_format': info.get('canvas_format', 'ppt169'),
                'page_count': info.get('page_count', 5),
                'primary_color': info.get('primary_color', ''),
            })
    return templates


def _list_chart_templates() -> list[dict]:
    """列出可用图表模板。"""
    charts_dir = PPT_TEMPLATES_DIR / 'charts'
    templates = []
    if charts_dir.exists():
        for f in sorted(charts_dir.glob('*.svg')):
            chart_id = f.stem
            # 美化名称
            name = chart_id.replace('_', ' ').title()
            templates.append({
                'id': chart_id,
                'name': name,
                'file': f.name,
            })
    return templates


def _build_preview_html(project_id: str) -> str:
    """为 workspace 中的 SVG 文件生成自包含预览 HTML（SVG 直接嵌入，图片 base64 内联）。"""
    ws = _get_workspace(project_id)
    svg_files = []
    # 优先级: svg_final > svg_output > workspace 根目录
    for sub in ['svg_final', 'svg_output']:
        d = ws / sub
        if d.exists():
            svg_files = sorted(d.glob('*.svg'))
            if svg_files:
                break
    if not svg_files:
        svg_files = sorted(ws.glob('*.svg'))

    if not svg_files:
        return None

    slides_html = []
    for i, svg_file in enumerate(svg_files, 1):
        svg_content = svg_file.read_text(encoding='utf-8', errors='replace')
        # 检查 SVG 中是否引用了本地图片，有的话尝试 base64 内联
        def _inline_images(match):
            img_path = match.group(1)
            # 尝试在 workspace 下找到图片
            candidates = [
                ws / img_path,
                ws / 'images' / Path(img_path).name,
                svg_file.parent / img_path,
            ]
            for candidate in candidates:
                if candidate.exists() and candidate.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                    with open(candidate, 'rb') as f:
                        b64 = base64.b64encode(f.read()).decode('ascii')
                    ext = candidate.suffix.lower().replace('.', '')
                    mime = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'
                    if ext == 'svg':
                        mime = 'image/svg+xml'
                    return f'href="data:{mime};base64,{b64}"'
            return match.group(0)  # keep original if not found

        svg_content = re.sub(r'href="([^"]+\.(?:png|jpg|jpeg|gif|webp|svg))"', _inline_images, svg_content)
        slides_html.append(f'''<div class="slide" id="slide-{i}">
  <div class="slide-label">第 {i} 页 / 共 {len(svg_files)} 页</div>
  {svg_content}
</div>''')

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PPT 预览 - {project_id}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#1a1a2e; color:#eee; font-family:"PingFang SC","Microsoft YaHei",sans-serif; }}
.toolbar {{ position:fixed; top:0; left:0; right:0; z-index:100;
  background:rgba(0,0,0,0.85); backdrop-filter:blur(10px);
  padding:12px 24px; display:flex; align-items:center; gap:16px;
  border-bottom:1px solid rgba(255,255,255,0.1); }}
.toolbar select {{ padding:6px 12px; border-radius:6px; border:1px solid #444;
  background:#2a2a3e; color:#eee; font-size:14px; cursor:pointer; }}
.toolbar button {{ padding:6px 16px; border-radius:6px; border:none; cursor:pointer;
  font-size:13px; transition:all .2s; }}
.btn-prev,.btn-next {{ background:#3a3a5e; color:#eee; }}
.btn-prev:hover,.btn-next:hover {{ background:#5a5a7e; }}
.btn-export {{ background:#e94560; color:#fff; }}
.slide-nav {{ color:#aaa; font-size:14px; }}
.container {{ padding-top:70px; display:flex; flex-direction:column; align-items:center; gap:32px;
  padding-bottom:60px; }}
.slide {{ width:960px; background:#fff; border-radius:8px; overflow:hidden;
  box-shadow:0 8px 32px rgba(0,0,0,0.4); transition:transform .2s; }}
.slide-label {{ padding:8px 16px; background:#f0f0f0; color:#333; font-size:13px;
  text-align:center; border-bottom:1px solid #ddd; }}
.slide svg {{ width:100%; height:auto; display:block; }}
.slide.hidden {{ display:none; }}
.toolbar .current {{ font-weight:bold; color:#e94560; }}
</style>
</head>
<body>
<div class="toolbar">
  <span class="slide-nav">PPT 预览</span>
  <select id="slideSelect"></select>
  <button class="btn-prev" onclick="prevSlide()">◀ 上一页</button>
  <button class="btn-next" onclick="nextSlide()">下一页 ▶</button>
  <span class="slide-nav" id="pageInfo"></span>
  <span style="flex:1"></span>
  <span style="color:#aaa;font-size:12px;">共 {len(svg_files)} 页</span>
</div>
<div class="container">
  {''.join(slides_html)}
</div>
<script>
let current = 1;
const total = {len(svg_files)};
const select = document.getElementById('slideSelect');
for (let i=1; i<=total; i++) select.add(new Option('第 '+i+' 页', i));
function showSlide(n) {{
  current = ((n-1+total)%total)+1;
  document.querySelectorAll('.slide').forEach((s,i)=>s.classList.toggle('hidden', i+1!==current));
  select.value = current;
  document.getElementById('pageInfo').textContent = current+' / '+total;
}}
select.onchange = ()=>showSlide(parseInt(select.value));
document.addEventListener('keydown', e => {{
  if (e.key === 'ArrowLeft') prevSlide();
  if (e.key === 'ArrowRight') nextSlide();
}});
function prevSlide(){{ showSlide(current-1); }}
function nextSlide(){{ showSlide(current+1); }}
showSlide(1);
</script>
</body>
</html>'''
    preview_path = ws / 'preview.html'
    preview_path.write_text(html, encoding='utf-8')
    return html


# ============================================================
# Preview HTTP Server (Snippet)
# ============================================================

class PreviewServer:
    """内嵌 HTTP Server，serve workspace 目录下的静态文件（预览用）。"""

    def __init__(self):
        self._port: int = 0
        self._server = None
        self._thread = None
        self._running = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return

        try:
            from http.server import HTTPServer, SimpleHTTPRequestHandler
        except ImportError:
            logger.error("无法导入 http.server")
            return

        self._port = _find_free_port(PREVIEW_PORT_START)

        class Handler(SimpleHTTPRequestHandler):
            # 添加 .pptx MIME 类型，确保浏览器触发下载而非显示乱码
            extensions_map = {
                **SimpleHTTPRequestHandler.extensions_map,
                '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                '.svg': 'image/svg+xml',
            }

            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(WORKSPACES_DIR), **kwargs)

            def log_message(self, format, *args):
                logger.debug(f"[Preview HTTP] {args[0]}")

            def end_headers(self):
                # CORS 允许跨域
                self.send_header('Access-Control-Allow-Origin', '*')
                super().end_headers()

        self._server = HTTPServer(('127.0.0.1', self._port), Handler)
        self._running = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"预览服务器已启动: http://127.0.0.1:{self._port}")

    def stop(self):
        if self._server:
            self._running = False
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
            logger.info("预览服务器已停止")


def _ensure_preview_server() -> PreviewServer:
    global _preview_server_instance
    with _preview_lock:
        if _preview_server_instance is None or not _preview_server_instance.running:
            _preview_server_instance = PreviewServer()
            _preview_server_instance.start()
        return _preview_server_instance


# ============================================================
# MCP 工具实现
# ============================================================

def _tool_workspace_init(project_id: str = None, canvas_format: str = 'ppt169') -> dict:
    """初始化 PPT 项目工作区。"""
    pid = project_id or f"ppt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    ws = _get_workspace(pid)

    # 创建子目录
    for sub in ['svg_output', 'svg_final', 'notes', 'images', 'sources']:
        (ws / sub).mkdir(exist_ok=True)

    # 创建 project_info.json
    info = {
        'project_id': pid,
        'canvas_format': canvas_format,
        'created_at': datetime.now().isoformat(),
        'status': 'initialized',
    }
    (ws / 'project_info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')

    return {
        'success': True,
        'project_id': pid,
        'workspace': str(ws),
        'canvas_format': canvas_format,
        'message': f'工作区已创建: {pid}。你可以用 ppt_file_write 写入 SVG 文件，用 ppt_parse_source 解析源文档。',
    }


def _tool_file_write(project_id: str, filename: str, content: str) -> dict:
    """写入文件到项目工作区。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    # 安全检查：防止路径穿越
    safe_name = Path(filename).name
    filepath = ws / safe_name
    filepath.write_text(content, encoding='utf-8')
    file_size = filepath.stat().st_size

    return {
        'success': True,
        'filename': safe_name,
        'path': str(filepath),
        'size': file_size,
        'message': f'文件已写入: {safe_name} ({file_size} bytes)',
    }


def _tool_file_read(project_id: str, filename: str) -> dict:
    """读取项目工作区中的文件。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)
    safe_name = Path(filename).name
    filepath = ws / safe_name

    if not filepath.exists():
        return {'success': False, 'error': f'文件不存在: {safe_name}'}

    content = filepath.read_text(encoding='utf-8', errors='replace')
    file_size = filepath.stat().st_size

    # 对超大文件截断返回
    max_len = 15000
    if len(content) > max_len:
        content = content[:max_len] + f'\n\n... (文件过大，已截断，完整大小: {file_size} bytes)'

    return {
        'success': True,
        'filename': safe_name,
        'content': content,
        'size': file_size,
    }


def _tool_file_read_base64(project_id: str, filename: str) -> dict:
    """以 base64 编码读取工作区中的文件（二进制安全，适用于 PPTX/PNG 等）。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)
    safe_name = Path(filename).name
    filepath = ws / safe_name

    if not filepath.exists():
        return {'success': False, 'error': f'文件不存在: {safe_name}'}

    file_size = filepath.stat().st_size
    with open(filepath, 'rb') as f:
        data = base64.b64encode(f.read()).decode('ascii')

    return {
        'success': True,
        'filename': safe_name,
        'size': file_size,
        'base64_size': len(data),
        'base64_data': data,
    }


def _tool_file_list(project_id: str) -> dict:
    """列出项目工作区中的所有文件。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    files = []
    for f in sorted(ws.rglob('*')):
        if f.is_file():
            rel = f.relative_to(ws)
            files.append({
                'name': str(rel).replace('\\', '/'),
                'size': f.stat().st_size,
                'modified': datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    return {
        'success': True,
        'project_id': project_id,
        'workspace': str(ws),
        'file_count': len(files),
        'files': files[:100],  # 限制返回数量
    }


def _tool_parse_source(project_id: str, source_path: str = None, source_url: str = None, source_content: str = None, content_name: str = 'uploaded_content.md') -> dict:
    """解析源文档或直接接受文本内容，存入项目工作区。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    output_file = ws / 'parsed_content.md'

    # 直接内容模式（平台上传文件后提取的文本）
    if source_content and source_content.strip():
        output_file.write_text(source_content, encoding='utf-8')
        content_len = len(source_content)
        return {
            'success': True,
            'project_id': project_id,
            'source_type': 'inline_text',
            'output_file': str(output_file),
            'content_preview': source_content[:2000],
            'content_length': content_len,
            'message': f'内容已写入工作区 ({content_len} 字符)。接下来使用 ppt_file_read 读取 parsed_content.md 获取全文进行分析。',
        }

    # URL 模式
    if source_url:
        result = _run_python_script(
            'source_to_md/web_to_md.py', source_url,
            cwd=str(ws), timeout=60,
        )
        if result['success']:
            # 查找生成的 md 文件
            md_files = list(ws.glob('*.md'))
            if md_files:
                content = md_files[0].read_text(encoding='utf-8', errors='replace')
                output_file.write_text(content, encoding='utf-8')
                return {
                    'success': True,
                    'project_id': project_id,
                    'source_type': 'url',
                    'source': source_url,
                    'output_file': str(output_file),
                    'content_preview': content[:2000],
                    'content_length': len(content),
                }
        return {'success': False, 'error': f'URL解析失败: {result.get("stderr", result.get("error", "未知错误"))}'}

    # 文件模式
    if source_path:
        source = Path(source_path)
        if not source.exists():
            return {'success': False, 'error': f'源文件不存在: {source_path}'}

        ext = source.suffix.lower()
        source_dest = ws / 'sources' / source.name
        source_dest.parent.mkdir(exist_ok=True)
        shutil.copy2(str(source), str(source_dest))

        # 根据扩展名选择解析器
        if ext == '.pdf':
            result = _run_python_script('source_to_md/pdf_to_md.py', str(source_dest), cwd=str(ws), timeout=120)
        elif ext in ('.docx', '.doc', '.odt', '.rtf', '.epub', '.html', '.htm', '.tex', '.rst', '.org'):
            result = _run_python_script('source_to_md/doc_to_md.py', str(source_dest), cwd=str(ws), timeout=120)
        elif ext in ('.xlsx', '.xlsm', '.xls'):
            result = _run_python_script('source_to_md/excel_to_md.py', str(source_dest), cwd=str(ws), timeout=120)
        elif ext in ('.pptx', '.pptm'):
            result = _run_python_script('source_to_md/ppt_to_md.py', str(source_dest), cwd=str(ws), timeout=120)
        elif ext in ('.md', '.markdown', '.txt'):
            content = source_dest.read_text(encoding='utf-8', errors='replace')
            output_file.write_text(content, encoding='utf-8')
            return {
                'success': True,
                'project_id': project_id,
                'source_type': ext,
                'source': str(source_dest),
                'output_file': str(output_file),
                'content_preview': content[:2000],
                'content_length': len(content),
            }
        else:
            return {'success': False, 'error': f'不支持的文件格式: {ext}'}

        if result['success']:
            md_files = sorted(ws.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True)
            if md_files:
                content = md_files[0].read_text(encoding='utf-8', errors='replace')
                output_file.write_text(content, encoding='utf-8')
                return {
                    'success': True,
                    'project_id': project_id,
                    'source_type': ext,
                    'source': str(source_dest),
                    'output_file': str(output_file),
                    'content_preview': content[:2000],
                    'content_length': len(content),
                }

        return {
            'success': False,
            'error': f'文档解析失败',
            'stdout': result.get('stdout', ''),
            'stderr': result.get('stderr', ''),
        }

    return {'success': False, 'error': '请提供 source_path 或 source_url'}


def _tool_list_templates(template_type: str = 'all') -> dict:
    """列出可用的PPT模板。"""
    result = {'success': True, 'templates': {}}

    if template_type in ('all', 'layout'):
        result['templates']['layouts'] = _list_layout_templates()

    if template_type in ('all', 'deck'):
        result['templates']['decks'] = _list_deck_templates()

    if template_type in ('all', 'chart'):
        result['templates']['charts'] = _list_chart_templates()

    total = sum(len(v) for v in result['templates'].values())
    result['total'] = total
    result['message'] = (
        f'共 {total} 个模板可用。'
        f'Layouts 提供页面布局风格，Decks 是完整品牌模板包，Charts 是图表模板。'
        f'选择模板后请告诉用户模板名称，用户确认后LLM可以开始生成SVG。'
    )
    return result


def _read_design_spec(template_type: str, template_name: str) -> str:
    """读取指定模板的 design_spec.md 内容。"""
    spec_path = PPT_TEMPLATES_DIR / template_type / template_name / 'design_spec.md'
    if spec_path.exists():
        try:
            return spec_path.read_text(encoding='utf-8')
        except Exception:
            pass
    return ''


def _tool_get_template(template_type: str, template_name: str) -> dict:
    """获取单个模板的完整信息，包含 design_spec 内容。"""
    if template_type not in ('layouts', 'decks', 'charts'):
        return {'success': False, 'error': f'type 必须为 layouts/decks/charts, 收到: {template_type}'}

    index_path = PPT_TEMPLATES_DIR / template_type / f'{template_type}_index.json'
    if not index_path.exists():
        return {'success': False, 'error': f'模板索引不存在: {template_type}'}

    with open(index_path, 'r', encoding='utf-8') as f:
        index = json.load(f)

    if template_name not in index:
        available = ', '.join(index.keys())
        return {'success': False, 'error': f'模板 "{template_name}" 不存在。可用: {available}'}

    info = index[template_name]
    design_spec = _read_design_spec(template_type, template_name)

    return {
        'success': True,
        'template': {
            'id': template_name,
            'type': template_type[:-1],  # layouts → layout
            'name': template_name,
            'summary': info.get('summary', ''),
            'canvas_format': info.get('canvas_format', 'ppt169'),
            'page_count': info.get('page_count', 5),
            'primary_color': info.get('primary_color', ''),
            'design_spec': design_spec,
            'design_spec_length': len(design_spec),
        },
        'message': f'已加载 {template_name} 的完整设计规范 ({len(design_spec)} 字符)。按 design_spec 的配色/字体/布局要求逐页生成 SVG。',
    }


def _tool_svg_to_pptx(project_id: str, merge_text: bool = True) -> dict:
    """将 workspace 中的 SVG 文件转换为 PPTX。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    # 检查是否有 SVG 文件（检查根目录和 svg_final）
    svg_final_dir = ws / 'svg_final'
    root_svgs = list(ws.glob('*.svg'))
    final_svgs = list(svg_final_dir.glob('*.svg')) if svg_final_dir.exists() else []
    if not root_svgs and not final_svgs:
        return {'success': False, 'error': '工作区中没有 SVG 文件。请先用 ppt_file_write 写入 SVG 页面。'}

    # Step 0: 将工作区根目录的 SVG 移入 svg_output/（svg_to_pptx 脚本默认读这个目录）
    svg_output_dir = ws / 'svg_output'
    svg_output_dir.mkdir(exist_ok=True)
    for svg_file in root_svgs:
        dest = svg_output_dir / svg_file.name
        if not dest.exists():
            shutil.copy2(str(svg_file), str(dest))
    if root_svgs:
        logger.info(f"已复制 {len(root_svgs)} 个 SVG → svg_output/")

    # Step 1: total_md_split (拆分讲稿笔记)
    _run_python_script('total_md_split.py', str(ws), cwd=str(PPT_MASTER_DIR), timeout=60)

    # Step 2: finalize_svg (嵌入图片、展平 tspan、修复宽高比等)
    finalize_result = _run_python_script('finalize_svg.py', str(ws), cwd=str(PPT_MASTER_DIR), timeout=120)
    if not finalize_result['success']:
        logger.warning(f"finalize_svg 警告: {finalize_result.get('stderr', finalize_result.get('error', ''))}")

    # Step 3: svg_to_pptx
    args = [str(ws)]
    if not merge_text:
        args.append('--no-merge')

    result = _run_python_script('svg_to_pptx.py', *args, cwd=str(PPT_MASTER_DIR), timeout=120)

    if result['success']:
        # svg_to_pptx 将 PPTX 写入 exports/ 子目录，需要找出来并拷贝到根目录
        exports_dir = ws / 'exports'
        pptx_files = list(exports_dir.glob('*.pptx')) if exports_dir.exists() else []
        if not pptx_files:
            pptx_files = list(ws.glob('*.pptx'))  # fallback
        if pptx_files:
            pptx_path = pptx_files[0]
            # 复制到工作区根目录，方便预览服务器和导出工具找到
            root_copy = ws / pptx_path.name
            if pptx_path != root_copy:
                shutil.copy2(str(pptx_path), str(root_copy))
            return {
                'success': True,
                'project_id': project_id,
                'pptx_file': str(root_copy),
                'pptx_name': root_copy.name,
                'pptx_size': root_copy.stat().st_size,
                'message': f'PPTX 已生成: {root_copy.name}（{root_copy.stat().st_size} bytes）。使用 ppt_export_pptx 获取下载链接。',
            }

    return {
        'success': False,
        'error': 'PPTX 生成失败',
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
    }


def _tool_render_preview(project_id: str) -> dict:
    """生成自包含预览 HTML，返回内容供 LLM 通过 file_save_to_download 保存。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}

    preview_html = _build_preview_html(project_id)
    if not preview_html:
        return {'success': False, 'error': '工作区中没有 SVG 文件，无法生成预览。'}

    # 保存到工作区
    preview_path = _get_workspace(project_id) / 'preview.html'
    preview_path.write_text(preview_html, encoding='utf-8')

    # 文件名固定
    preview_filename = 'preview.html'
    html_b64 = base64.b64encode(preview_html.encode('utf-8')).decode('ascii')

    return {
        'success': True,
        'project_id': project_id,
        'preview_filename': preview_filename,
        'html_base64': html_b64,
        'html_size': len(preview_html),
        'message': (
            f'请调用 file_save_to_download(filename="{project_id}_preview.html", '
            f'content=<html_base64>, encoding="base64") 保存预览文件，'
            f'然后将返回的 download_url 用 markdown 链接展示给用户。'
        ),
    }


def _tool_export_pptx(project_id: str, output_name: str = None) -> dict:
    """导出 PPTX — 返回文件名，LLM 用 ppt_file_read_base64 获取 base64 后调 file_save_to_download。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    # 搜索 exports/ 和根目录，将 PPTX 拷贝到根目录方便读取
    pptx_files = []
    exports_dir = ws / 'exports'
    if exports_dir.exists():
        pptx_files = list(exports_dir.glob('*.pptx'))
    if not pptx_files:
        pptx_files = list(ws.glob('*.pptx'))
    if not pptx_files:
        return {'success': False, 'error': '工作区中没有 PPTX 文件。请先调用 ppt_svg_to_pptx 生成。'}

    pptx_path = pptx_files[0]
    export_name = output_name or pptx_path.name
    # 确保 .pptx 后缀
    if not export_name.lower().endswith('.pptx'):
        export_name += '.pptx'
    file_size = pptx_path.stat().st_size
    size_mb = file_size / (1024 * 1024)

    # 拷贝到根目录
    root_copy = ws / export_name
    if pptx_path != root_copy:
        shutil.copy2(str(pptx_path), str(root_copy))

    # Base64 编码
    with open(pptx_path, 'rb') as f:
        base64_data = base64.b64encode(f.read()).decode('ascii')

    return {
        'success': True,
        'filename': export_name,
        'size': file_size,
        'size_mb': round(size_mb, 2),
        'base64_data': base64_data,
        'message': (
            f'请调用 file_save_to_download(filename="{export_name}", '
            f'content=<base64_data>, encoding="base64") 保存 PPTX 文件，'
            f'然后将返回的 download_url 用 markdown 链接展示给用户。'
        ),
    }


def _tool_get_info(project_id: str) -> dict:
    """获取项目工作区信息。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    svg_files = sorted(ws.glob('*.svg'))
    pptx_files = list(ws.glob('*.pptx'))
    has_preview = (ws / 'preview.html').exists()

    return {
        'success': True,
        'project_id': project_id,
        'workspace': str(ws),
        'svg_count': len(svg_files),
        'svg_files': [f.name for f in svg_files],
        'pptx_files': [f.name for f in pptx_files],
        'has_preview': has_preview,
    }


def _tool_project_cleanup(project_id: str) -> dict:
    """清理项目工作区。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)
    if ws.exists():
        shutil.rmtree(str(ws))
        return {'success': True, 'message': f'工作区 {project_id} 已清理'}
    return {'success': False, 'error': f'工作区 {project_id} 不存在'}


def _tool_generate_image(
    project_id: str,
    prompt: str,
    aspect_ratio: str = '16:9',
    image_size: str = '1K',
    backend: str = None,
    negative_prompt: str = '',
) -> dict:
    """调用 AI 图像生成。支持 OpenAI DALL-E、Gemini、Stability 等后端。"""
    if not project_id:
        return {'success': False, 'error': '请提供 project_id'}
    ws = _get_workspace(project_id)

    images_dir = ws / 'images'
    images_dir.mkdir(exist_ok=True)

    output_path = images_dir / f'gen_{uuid.uuid4().hex[:8]}.png'

    # 通过 manifest 模式调用 image_gen.py（新格式: {"items": [...]}）
    manifest = {
        "items": [{
            "filename": str(output_path.name),
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
            "status": "Pending",
        }]
    }
    manifest_path = images_dir / 'image_prompts.json'
    with open(manifest_path, 'w', encoding='utf-8') as mf:
        json.dump(manifest, mf, ensure_ascii=False, indent=2)

    # 构建 image_gen.py 调用参数
    gen_args = ['--manifest', str(manifest_path)]
    if backend:
        gen_args.extend(['--backend', backend])

    result = _run_python_script(
        'image_gen.py', *gen_args,
        cwd=str(PPT_MASTER_DIR), timeout=120,
    )

    if result['success'] and output_path.exists():
        # Base64 编码返回
        with open(output_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('ascii')
        return {
            'success': True,
            'project_id': project_id,
            'image_path': str(output_path),
            'image_name': output_path.name,
            'image_size': output_path.stat().st_size,
            'base64': img_b64,
            'message': f'图像已生成: {output_path.name} ({output_path.stat().st_size} bytes)',
        }

    return {
        'success': False,
        'error': 'AI 图像生成失败',
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'hint': f'可用的图像后端: openai, gemini, stability, zhipu, siliconflow, minimax, qwen, etc. 请在 ppt-master-main/.env 中配置 IMAGE_BACKEND 和对应 API Key。',
    }


# ============================================================
# MCP Server 构建
# ============================================================

def create_mcp_server() -> FastMCP:
    """创建并配置 MCP Server 实例。"""
    mcp = FastMCP(
        name='PPT Master MCP Server', host="0.0.0.0", port=8011, json_response=True,
        instructions='PPT Master - AI驱动的PPT生成服务。支持源文档解析、SVG编辑、模板浏览、预览和PPTX导出。',
    )

    # ── Workspace 管理 ──
    @mcp.tool()
    async def ppt_workspace_init(
        project_id: str = None,
        canvas_format: str = 'ppt169',
    ) -> str:
        """初始化 PPT 项目工作区。创建一个新的项目目录，包含 svg_output/、notes/、images/ 等子目录。

        Args:
            project_id: 项目ID（可选，不提供则自动生成）
            canvas_format: 画布格式，默认 ppt169 (16:9)
        """
        result = _tool_workspace_init(project_id, canvas_format)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def ppt_get_info(project_id: str) -> str:
        """获取项目工作区的当前状态信息。

        Args:
            project_id: 项目ID
        """
        result = _tool_get_info(project_id)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def ppt_project_cleanup(project_id: str) -> str:
        """清理（删除）指定的项目工作区。

        Args:
            project_id: 项目ID
        """
        result = _tool_project_cleanup(project_id)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── 文件操作 ──
    @mcp.tool()
    async def ppt_file_write(project_id: str, filename: str, content: str,
                             file_name: Optional[str] = None,
                             svg_content: Optional[str] = None,
                             svg: Optional[str] = None,
                             data: Optional[str] = None) -> str:
        """将内容写入项目工作区的文件。适合写入 SVG 页面、Markdown 笔记等。

        Args:
            project_id: 项目ID
            filename: 文件名（如 slide_01.svg）（标准参数名，必填）
            content: 文件内容（标准参数名，必填）
            file_name: 兼容字段，若 filename 为空而本字段有值则作为文件名使用
            svg_content: 兼容字段，若 content 为空而本字段有值则作为内容使用
            svg: 同 svg_content（兼容字段）
            data: 同 svg_content（兼容字段）
        """
        # 兼容 LLM 偶发用错参数名的情况
        actual_filename = filename or file_name or ''
        actual_content = content or svg_content or svg or data or ''
        if not filename and file_name:
            logger.warning(
                f"ppt_file_write 兼容模式: filename 为空，已回退到 file_name "
                f"(file_name={file_name}, project_id={project_id})"
            )
        if not content and (svg_content or svg or data):
            logger.warning(
                f"ppt_file_write 兼容模式: content 为空，已回退到 svg_content/svg/data "
                f"(filename={actual_filename}, project_id={project_id})"
            )
        result = _tool_file_write(project_id, actual_filename, actual_content)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def ppt_file_read(project_id: str, filename: str,
                            file_name: Optional[str] = None,
                            file_path: Optional[str] = None,
                            path: Optional[str] = None) -> str:
        """读取项目工作区中的文件内容。

        Args:
            project_id: 项目ID
            filename: 文件名（标准参数名）
            file_name: 兼容字段，若 filename 为空而本字段有值则作为文件名使用
            file_path: 兼容字段，若 filename 为空而本字段有值则作为文件名使用（仅取 basename）
            path: 同 file_path（兼容字段）
        """
        # 兼容 LLM 偶发用错参数名：filename 为空时回退到 file_name/file_path/path
        actual_filename = filename or file_name or file_path or path or ''
        if not filename and (file_name or file_path or path):
            logger.warning(
                f"ppt_file_read 兼容模式: filename 为空，已回退到 file_name/file_path/path "
                f"(actual_filename={actual_filename}, project_id={project_id})"
            )
        result = _tool_file_read(project_id, actual_filename)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def ppt_file_read_base64(project_id: str, filename: str) -> str:
        """以 base64 编码读取工作区中的文件。适合读取生成的 PPTX、PNG 等二进制文件，获取 base64 后调 file_save_to_download 保存到平台。

        Args:
            project_id: 项目ID
            filename: 文件名（如 'output.pptx'、'preview.html'）
        """
        result = _tool_file_read_base64(project_id, filename)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def ppt_file_list(project_id: str) -> str:
        """列出项目工作区中的所有文件。

        Args:
            project_id: 项目ID
        """
        result = _tool_file_list(project_id)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── 源文档解析 ──
    @mcp.tool()
    async def ppt_parse_source(
        project_id: str,
        source_path: str = None,
        source_url: str = None,
        source_content: str = None,
    ) -> str:
        """解析源文档或直接接受文本内容。当用户上传了文件且平台已提取文本时，将提取的文本通过 source_content 参数传入。

        Args:
            project_id: 项目ID
            source_path: 本地源文件路径（PDF/DOCX/PPTX/XLSX/MD等）
            source_url: 源文件URL（网页链接）
            source_content: 直接传入的文本内容（当平台已提取上传文件内容时使用此参数）
        """
        result = _tool_parse_source(project_id, source_path, source_url, source_content)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── 模板浏览 ──
    @mcp.tool()
    async def ppt_list_templates(template_type: str = 'all') -> str:
        """列出所有可用的PPT模板（摘要，不含完整设计规范）。返回值包含模板ID/名称/摘要/配色。

        Args:
            template_type: 模板类型，可选 'all'/'layout'/'deck'/'chart'
        """
        result = _tool_list_templates(template_type)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def ppt_get_template(template_type: str, template_name: str) -> str:
        """获取单个模板的完整设计规范（design_spec），包含配色/字体/布局详则。
        在 ppt_list_templates 中选择模板后，调用本工具获取该模板的完整规范。

        Args:
            template_type: 模板类型，'layouts' / 'decks' / 'charts'
            template_name: 模板ID/名称，来自 ppt_list_templates 返回的 id 字段
        """
        result = _tool_get_template(template_type, template_name)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── SVG → PPTX 导出 ──
    @mcp.tool()
    async def ppt_svg_to_pptx(project_id: str, merge_text: bool = True) -> str:
        """将工作区中的 SVG 文件转换为可编辑的 PPTX 文件。

        Args:
            project_id: 项目ID
            merge_text: 是否合并相邻文本框（默认True，推荐）
        """
        result = _tool_svg_to_pptx(project_id, merge_text)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── 预览 ──
    @mcp.tool()
    async def ppt_render_preview(project_id: str) -> str:
        """生成自包含预览HTML，返回html_base64。拿到后必须调用file_save_to_download(encoding='base64')保存到平台获取预览链接。

        Args:
            project_id: 项目ID
        """
        result = _tool_render_preview(project_id)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── 导出 ──
    @mcp.tool()
    async def ppt_export_pptx(project_id: str, output_name: str = None) -> str:
        """生成PPTX文件并返回base64编码。拿到base64_data后必须调用file_save_to_download(encoding='base64')保存到平台获取下载链接。

        Args:
            project_id: 项目ID
            output_name: 输出文件名（可选）
        """
        result = _tool_export_pptx(project_id, output_name)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # ── AI 图像生成 ──
    if PPT_IMAGE_GEN_ENABLED:
        logger.info("AI 图像生成功能已启用")

        @mcp.tool()
        async def ppt_generate_image(
            project_id: str,
            prompt: str,
            aspect_ratio: str = '16:9',
            image_size: str = '1K',
            backend: str = None,
            negative_prompt: str = '',
        ) -> str:
            """调用 AI 图像生成模型为 PPT 生成配图。生成后图片存入工作区 images/ 目录。

            返回 JSON 含 image_name (如 gen_abc123.png) 和 base64 数据。
            生成后必须在 SVG 中用 <image> 标签引用该图片，href 写相对路径:
              <image href="images/gen_abc123.png" x="..." y="..." width="..." height="..."/>

            用法示例:
              1. ppt_generate_image(project_id, prompt="modern office building")
              2. 从返回的 image_name 拿到文件名，在SVG中引用 images/xxx.png
              3. 在 ppt_file_write 的SVG内容中添加 <image href="images/xxx.png" .../>

            不指定 backend 时自动使用 .env 中 IMAGE_BACKEND 配置的后端（当前: siliconflow）。

            Args:
                project_id: 项目ID
                prompt: 图像生成提示词（英文描述效果最佳）
                aspect_ratio: 宽高比，默认 '16:9'
                image_size: 图像质量 '1K'/'2K'/'4K'
                backend: 图像后端（可选，不指定则用 .env 配置）。可选: siliconflow, openai, gemini, zhipu, qwen, volcengine 等
                negative_prompt: 负面提示词（可选）
            """
            result = _tool_generate_image(project_id, prompt, aspect_ratio, image_size, backend, negative_prompt)
            return json.dumps(result, ensure_ascii=False, indent=2)
    else:
        logger.info("AI 图像生成功能已关闭（PPT_IMAGE_GEN_ENABLED=false）")

    return mcp


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='PPT Master MCP Server')
    parser.add_argument('--port', type=int, default=8011, help='MCP Server 端口 (默认 8011)')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='绑定地址 (默认 0.0.0.0)')
    parser.add_argument('--transport', type=str, default='sse', choices=['sse', 'stdio'], help='传输模式 (默认 sse)')
    args = parser.parse_args()

    if not HAS_FASTMCP:
        logger.error("FastMCP 未安装。请运行: pip install mcp")
        sys.exit(1)

    # 确保 workspaces 目录存在
    _ensure_workspaces()

    logger.info(f"PPT Master MCP Server 启动中...")
    logger.info(f"  - ppt-master 路径: {PPT_MASTER_DIR}")
    logger.info(f"  - 工作区目录: {WORKSPACES_DIR}")
    logger.info(f"  - 模板目录: {PPT_TEMPLATES_DIR}")
    logger.info(f"  - AI 图像生成: {'已启用' if PPT_IMAGE_GEN_ENABLED else '已关闭（PPT_IMAGE_GEN_ENABLED=false）'}")

    mcp = create_mcp_server()

    if args.transport == 'stdio':
        logger.info("使用 stdio 传输模式")
        mcp.run(transport='stdio')
    else:
        logger.info(f"使用 SSE 传输模式: http://{args.host}:{args.port}/sse")
        mcp.run(transport="streamable-http")


if __name__ == '__main__':
    main()
