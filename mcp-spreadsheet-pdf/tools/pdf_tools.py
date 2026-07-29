"""
PDF 工具模块

提供 PDF 文件操作：读取文本、创建、合并、拆分、提取页面、获取元信息。

工具列表:
- pdf_read_text      提取 PDF 文本内容
- pdf_get_info        获取 PDF 元信息（页数、大小、加密状态等）
- pdf_merge           合并多个 PDF 为一个
- pdf_split           拆分 PDF（按页范围提取）
- pdf_extract_page   提取指定页面为新 PDF
- pdf_create         从文本生成 PDF 文件
"""

import os
import json
from mcp.server.fastmcp import FastMCP


def _import_pypdf2():
    try:
        import PyPDF2
        return PyPDF2
    except ImportError:
        return None


def _import_pdfplumber():
    try:
        import pdfplumber
        return pdfplumber
    except ImportError:
        return None


def _import_reportlab():
    try:
        from reportlab.pdfgen import canvas as Canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        return Canvas, A4, pdfmetrics, TTFont
    except ImportError:
        return None


def _find_chinese_font(prefer: str = ""):
    """自动查找系统中文字体路径

    Args:
        prefer: 优先字体名（如 "仿宋"），为空则按优先级返回第一个找到的
    """
    fonts_dir = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts') if os.name == 'nt' else ''

    # (中文名, 文件名, Linux包名)
    font_registry = [
        ('仿宋_GB2312',     'simfang.ttf',               'fonts-arphic-uming'),
        ('仿宋',            'simfang.ttf',               'fonts-arphic-uming'),
        ('楷体_GB2312',     'simkai.ttf',                'fonts-arphic-ukai'),
        ('楷体',            'simkai.ttf',                'fonts-arphic-ukai'),
        ('黑体',            'simhei.ttf',                'fonts-wqy-zenhei'),
        ('宋体',            'simsun.ttc',                'fonts-wqy-zenhei'),
        ('微软雅黑',         'msyh.ttc',                  'fonts-wqy-microhei'),
        ('微软雅黑Bold',     'msyhbd.ttc',                'fonts-wqy-microhei'),
        ('方正小标宋简体',    'FZXBSJW.TTF',               None),
        ('方正小标宋',        'FZXBSJW.TTF',               None),
        ('方正小标宋简体',    '方正小标宋简.TTF',           None),  # Docker 自定义字体
        ('文泉驿正黑',        'wqy-zenhei.ttc',            'fonts-wqy-zenhei'),
        ('文泉驿微米黑',      'wqy-microhei.ttc',          'fonts-wqy-microhei'),
    ]

    if prefer:
        # 精确匹配优先字体
        for name, filename, _ in font_registry:
            if name == prefer:
                if fonts_dir:
                    path = os.path.join(fonts_dir, filename)
                    if os.path.exists(path):
                        return path
                else:
                    for base in ['/usr/share/fonts/truetype', '/usr/share/fonts/opentype']:
                        if os.path.exists(base):
                            try:
                                for root, _, files in os.walk(base):
                                    for f in files:
                                        if f.lower() == filename.lower():
                                            return os.path.join(root, f)
                            except (OSError, PermissionError):
                                continue
                return None  # 指定字体未找到，不回退

    # 按顺序查找任意可用字体
    for name, filename, _ in font_registry:
        if fonts_dir:
            path = os.path.join(fonts_dir, filename)
            if os.path.exists(path):
                return path
        else:
            # Linux: 额外搜索常见路径
            for base in ['/usr/share/fonts/truetype/wqy',
                         '/usr/share/fonts/opentype/noto',
                         '/usr/share/fonts/truetype/droid',
                         '/usr/share/fonts/truetype/arphic']:
                path = os.path.join(base, filename)
                if os.path.exists(path):
                    return path

    # 兜底：Linux 下遍历常见目录
    if not fonts_dir:
        for base in ['/usr/share/fonts/truetype', '/usr/share/fonts/opentype']:
            if os.path.exists(base):
                try:
                    for root, _, files in os.walk(base):
                        for f in files:
                            if f.lower().endswith(('.ttf', '.ttc', '.otf')):
                                return os.path.join(root, f)
                except (OSError, PermissionError):
                    continue

    return None


def _safe_register_font(font_path: str, pdfmetrics, TTFont) -> str:
    """安全注册 TTF/TTC 字体，返回 register 名，失败返回空字符串"""
    try:
        reg_name = os.path.splitext(os.path.basename(font_path))[0]
        try:
            pdfmetrics.registerFont(TTFont(reg_name, font_path))
        except Exception:
            return ""  # 注册失败，不回退到无效字体名
        return reg_name
    except Exception:
        return ""


def _has_chinese(text: str) -> bool:
    """检测文本是否包含中文字符"""
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)


def _resolve_safe_path(path: str, base_dir: str) -> str:
    if os.path.isabs(path):
        if not path.startswith(os.path.abspath(base_dir)):
            raise ValueError(f"路径越权: {path}")
        return path
    return os.path.join(base_dir, path)


def register_pdf_tools(mcp: FastMCP, base_dir: str = "/data", **kwargs):
    """注册 PDF 工具"""

    # ==========================================
    # 读取文本
    # ==========================================

    @mcp.tool()
    async def pdf_read_text(
        path: str,
        start_page: int = 1,
        end_page: int = 0,
        max_chars: int = 50000,
    ) -> str:
        """提取 PDF 文本内容（基于 pdfplumber，提取精度高）。

        Args:
            path: PDF 文件路径
            start_page: 起始页码（从 1 开始），默认 1
            end_page: 结束页码（含），0 表示到最后一页
            max_chars: 最大返回字符数，默认 50000

        Returns:
            JSON: {"status":"ok", "total_pages":N, "extracted_pages":N, "text":"..."}
        """
        try:
            pdfplumber = _import_pdfplumber()
            if pdfplumber is None:
                return json.dumps({"error": "pdfplumber 未安装。请执行: pip install pdfplumber"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            all_text = []
            extracted = 0
            sep = '\n\n'

            with pdfplumber.open(target) as pdf:
                total = len(pdf.pages)
                if start_page > total:
                    return json.dumps({"error": f"起始页码 {start_page} 超出总页数 {total}"}, ensure_ascii=False)

                end = end_page if end_page > 0 else total
                end = min(end, total)

                for i in range(start_page - 1, end):
                    page = pdf.pages[i]
                    page_text = page.extract_text()
                    if page_text:
                        all_text.append(f"--- 第 {i + 1} 页 ---\n{page_text}")
                        extracted += 1

                    if len(sep.join(all_text)) > max_chars:
                        break

            full_text = sep.join(all_text)[:max_chars]

            return json.dumps({
                "status": "ok",
                "file": path,
                "total_pages": total,
                "extracted_pages": extracted,
                "char_count": len(full_text),
                "truncated": len('\n\n'.join(all_text)) > max_chars,
                "text": full_text,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 获取信息
    # ==========================================

    @mcp.tool()
    async def pdf_get_info(path: str) -> str:
        """获取 PDF 文件元信息：页数、文件大小、是否加密、作者/标题（如有）。

        Args:
            path: PDF 文件路径

        Returns:
            JSON: {"status":"ok", "page_count":N, "file_size_mb":X, "encrypted":bool, "metadata":{...}}
        """
        try:
            PyPDF2 = _import_pypdf2()
            if PyPDF2 is None:
                return json.dumps({"error": "PyPDF2 未安装。请执行: pip install PyPDF2"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            file_size = os.path.getsize(target)

            with open(target, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                page_count = len(reader.pages)
                encrypted = reader.is_encrypted

                metadata = {}
                if reader.metadata:
                    for key in ('/Title', '/Author', '/Subject', '/Creator', '/Producer'):
                        val = reader.metadata.get(key)
                        if val:
                            metadata[key.lstrip('/').lower()] = str(val)

            return json.dumps({
                "status": "ok",
                "file": path,
                "page_count": page_count,
                "file_size_mb": round(file_size / 1048576, 2),
                "file_size_bytes": file_size,
                "encrypted": encrypted,
                "metadata": metadata,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 合并
    # ==========================================

    @mcp.tool()
    async def pdf_merge(paths: str, output_filename: str = "merged.pdf") -> str:
        """合并多个 PDF 文件为一个。

        Args:
            paths: JSON 数组，多个 PDF 文件的路径 '["a.pdf","b.pdf"]'
            output_filename: 输出文件名，默认 "merged.pdf"

        Returns:
            JSON: {"status":"ok", "output_path":"...", "source_count":N, "total_pages":N}
        """
        try:
            PyPDF2 = _import_pypdf2()
            if PyPDF2 is None:
                return json.dumps({"error": "PyPDF2 未安装"}, ensure_ascii=False)

            pdf_paths = json.loads(paths)
            if not isinstance(pdf_paths, list) or len(pdf_paths) < 2:
                return json.dumps({"error": "paths 必须是至少2个路径的 JSON 数组"}, ensure_ascii=False)

            merger = PyPDF2.PdfMerger()
            total_pages = 0

            for p in pdf_paths:
                target = _resolve_safe_path(p, base_dir)
                if not os.path.exists(target):
                    merger.close()
                    return json.dumps({"error": f"文件不存在: {p}"}, ensure_ascii=False)
                merger.append(target)
                reader = PyPDF2.PdfReader(target)
                total_pages += len(reader.pages)

            output = _resolve_safe_path(output_filename, base_dir)
            os.makedirs(os.path.dirname(output), exist_ok=True)
            merger.write(output)
            merger.close()

            return json.dumps({
                "status": "ok",
                "output_path": output,
                "source_count": len(pdf_paths),
                "total_pages": total_pages,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 拆分
    # ==========================================

    @mcp.tool()
    async def pdf_split(
        path: str,
        page_ranges: str = "",
        split_every: int = 0,
    ) -> str:
        """拆分 PDF 文件。两种模式:
        1. 按页面范围拆分: page_ranges="1-3,5-5,7-10"
        2. 按每N页拆一份: split_every=2 (每2页一个文件)

        Args:
            path: PDF 文件路径
            page_ranges: 页码范围，如 "1-3,5-5,7-10"
            split_every: 每 N 页拆一份，如 2 表示每2页一个文件

        Returns:
            JSON: {"status":"ok", "output_files":[...], "total_files":N}
        """
        try:
            PyPDF2 = _import_pypdf2()
            if PyPDF2 is None:
                return json.dumps({"error": "PyPDF2 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            reader = PyPDF2.PdfReader(target)
            total_pages = len(reader.pages)
            output_files = []

            stem = os.path.splitext(os.path.basename(path))[0]
            out_dir = os.path.dirname(target)

            if page_ranges:
                # 按页码范围拆分
                ranges = []
                for part in page_ranges.split(','):
                    part = part.strip()
                    if '-' in part:
                        a, b = part.split('-', 1)
                        ranges.append((int(a) - 1, min(int(b), total_pages)))
                    else:
                        p = int(part) - 1
                        ranges.append((p, p + 1))

                for idx, (start, end) in enumerate(ranges):
                    writer = PyPDF2.PdfWriter()
                    for i in range(start, end):
                        writer.add_page(reader.pages[i])
                    out_name = f"{stem}_part{idx + 1}_p{start + 1}-{end}.pdf"
                    out_path = os.path.join(out_dir, out_name)
                    with open(out_path, 'wb') as f:
                        writer.write(f)
                    output_files.append(out_path)

            elif split_every > 0:
                # 按每N页拆分
                part_num = 1
                for i in range(0, total_pages, split_every):
                    writer = PyPDF2.PdfWriter()
                    end_idx = min(i + split_every, total_pages)
                    for j in range(i, end_idx):
                        writer.add_page(reader.pages[j])
                    out_name = f"{stem}_part{part_num}_p{i + 1}-{end_idx}.pdf"
                    out_path = os.path.join(out_dir, out_name)
                    with open(out_path, 'wb') as f:
                        writer.write(f)
                    output_files.append(out_path)
                    part_num += 1
            else:
                return json.dumps({"error": "请指定 page_ranges 或 split_every"}, ensure_ascii=False)

            return json.dumps({
                "status": "ok",
                "source": path,
                "total_pages": total_pages,
                "total_files": len(output_files),
                "output_files": output_files,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def pdf_extract_page(path: str, page: int, output_filename: str = "") -> str:
        """提取 PDF 中的单页为新 PDF 文件。

        Args:
            path: PDF 文件路径
            page: 要提取的页码（从 1 开始）
            output_filename: 输出文件名，不填则自动生成

        Returns:
            JSON: {"status":"ok", "output_path":"...", "extracted_page":N}
        """
        try:
            PyPDF2 = _import_pypdf2()
            if PyPDF2 is None:
                return json.dumps({"error": "PyPDF2 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            reader = PyPDF2.PdfReader(target)
            total_pages = len(reader.pages)

            if page < 1 or page > total_pages:
                return json.dumps({"error": f"页码超出范围: {page}（共 {total_pages} 页）"}, ensure_ascii=False)

            writer = PyPDF2.PdfWriter()
            writer.add_page(reader.pages[page - 1])

            if not output_filename:
                stem = os.path.splitext(os.path.basename(path))[0]
                output_filename = f"{stem}_p{page}.pdf"

            output = _resolve_safe_path(output_filename, base_dir)
            os.makedirs(os.path.dirname(output), exist_ok=True)

            with open(output, 'wb') as f:
                writer.write(f)

            return json.dumps({
                "status": "ok",
                "output_path": output,
                "source": path,
                "extracted_page": page,
                "total_pages": total_pages,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 创建
    # ==========================================

    @mcp.tool()
    async def pdf_create(
        text: str,
        output_filename: str = "output.pdf",
        font_size: float = 14,
        alignment: str = "left",
        font_name: str = "default",
        return_base64: bool = False,
    ) -> str:
        """从文本生成 PDF 文件。

        Args:
            text: 要写入的文本内容（支持 \\n 换行）
            output_filename: 输出文件名，默认 "output.pdf"
            font_size: 字号，默认 14
            alignment: 对齐方式，"left"/"center"/"right"，默认 "left"
            font_name: 字体名，支持中文名称（"仿宋"/"仿宋_GB2312"/"楷体"/"楷体_GB2312"/"黑体"/"微软雅黑"/"方正小标宋简体"），
                       也支持 .ttf/.ttc 文件路径，"default"=自动选仿宋_GB2312
            return_base64: 是否在响应中直接返回 PDF 的 base64 编码，默认 False。
                          设为 True 后，响应 JSON 中会包含 "base64_content" 字段。
                          
                          【推荐用法】生成后直接保存为下载文件（一步到位）：
                          1. 调用 pdf_create(text="xxx", return_base64=True)
                          2. 从返回 JSON 中提取 base64_content 字段的值
                          3. 调用 file_save_to_download(filename="xxx.pdf", content="<base64_content的值>", encoding="base64")

        Returns:
            JSON: {"status":"ok", "output_path":"...", "base64_content":"...", "text_length":N, "pages":N, "font_used":"..."}
            return_base64=True 时，base64_content 字段为完整的 PDF 文件 base64 编码字符串，
            直接传给 file_save_to_download(content=该值, encoding="base64") 即可保存。
        """
        try:
            deps = _import_reportlab()
            if deps is None:
                return json.dumps({"error": "reportlab 未安装。请执行: pip install reportlab"}, ensure_ascii=False)
            Canvas, A4, pdfmetrics, TTFont = deps

            output = _resolve_safe_path(output_filename, base_dir)
            os.makedirs(os.path.dirname(output), exist_ok=True)

            width, height = A4
            c = Canvas.Canvas(output, pagesize=A4)

            # 字体设置
            effective_font = "Helvetica"
            font_display = "Helvetica"
            target_font_path = None

            if font_name and font_name != "default":
                # 用户指定字体
                if os.path.exists(font_name):
                    # 直接文件路径
                    target_font_path = font_name
                    font_display = os.path.splitext(os.path.basename(font_name))[0]
                else:
                    # 友好名称查找
                    target_font_path = _find_chinese_font(prefer=font_name)
                    if not target_font_path:
                        return json.dumps({
                            "error": f"未找到字体 '{font_name}'",
                            "hint": "请确认字体名称正确，或直接传入 .ttf/.ttc 文件路径。"
                                    "Docker 环境需先安装字体包。"
                        }, ensure_ascii=False)
                    font_display = font_name
            elif _has_chinese(text):
                # 中文文本：优先仿宋_GB2312
                target_font_path = _find_chinese_font(prefer="仿宋_GB2312")
                used_prefer = True
                if not target_font_path:
                    target_font_path = _find_chinese_font()  # 兜底找任意中文字体
                    used_prefer = False
                font_display = "仿宋_GB2312" if (target_font_path and used_prefer) else ("auto-detected" if target_font_path else "Helvetica")

            if target_font_path:
                reg_name = _safe_register_font(target_font_path, pdfmetrics, TTFont)
                if reg_name:
                    effective_font = reg_name
                else:
                    cjk_font = _find_chinese_font()  # 兜底
                    if cjk_font:
                        reg_name = _safe_register_font(cjk_font, pdfmetrics, TTFont)
                        if reg_name:
                            effective_font = reg_name
                            font_display = "auto-detected"

            if _has_chinese(text) and effective_font == "Helvetica":
                return json.dumps({
                    "error": "文本包含中文但系统中未找到中文字体",
                    "hint": "Docker: apt-get install -y fonts-wqy-zenhei；或通过 font_name 参数传入 .ttf/.ttc 路径"
                }, ensure_ascii=False)

            c.setFont(effective_font, font_size)

            # 对齐计算
            margin_left = 50
            margin_right = width - 50
            top = height - 50
            line_height = font_size * 1.5

            align = alignment.lower()
            y = top
            page_num = 1

            for line in text.split('\n'):
                if y < 50:
                    c.showPage()
                    c.setFont(effective_font, font_size)
                    y = top
                    page_num += 1

                if align == "center":
                    c.drawCentredString(width / 2, y, line)
                elif align == "right":
                    c.drawRightString(margin_right, y, line)
                else:
                    c.drawString(margin_left, y, line)

                y -= line_height

            c.save()

            result = {
                "status": "ok",
                "output_path": output,
                "filename": output_filename,
                "text_length": len(text),
                "line_count": len(text.split('\n')),
                "font_size": font_size,
                "font_used": font_display,
                "alignment": alignment,
                "pages": page_num,
            }

            if return_base64:
                import base64
                with open(output, 'rb') as f:
                    result["base64_content"] = base64.b64encode(f.read()).decode('ascii')

            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    print("[mcp-spreadsheet-pdf] PDF 工具已注册", flush=True)
