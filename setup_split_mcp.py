# -*- coding: utf-8 -*-
"""拆分 my-mcp-server：生成 mcp-form-fill / mcp-office-word / mcp-office-excel / mcp-office-pdf

- mcp-office-excel/tools/excel_tools.py = 原 excel_tools.py 去掉智能填表段（CRUD only）
- mcp-form-fill/tools/excel_form_tools.py = 原 excel_tools.py 智能填表段（parse/fill/smart_fill_excel）独立自包含
"""
import os
import shutil

BASE = r"e:\Python_Project\work_plication\my-mcp-server"
FD = os.path.join(BASE, "mcp-file-doc")
SP = os.path.join(BASE, "mcp-spreadsheet-pdf")

NEW = {
    "mcp-form-fill": 19120,
    "mcp-office-word": 19121,
    "mcp-office-excel": 19122,
    "mcp-office-pdf": 19123,
}

def w(path, content, mode="w", encoding="utf-8"):
    with open(path, mode, encoding=encoding) as f:
        f.write(content)

def r(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

# ---------- 1. 创建目录 ----------
for name in NEW:
    for sub in ("", "tools", "config"):
        os.makedirs(os.path.join(BASE, name, sub), exist_ok=True)

# ---------- 2. 复制公共模块 ----------
# form-fill：Word 填表（auto_fill） + Excel 填表（截取） + 文件传输3 + 同义词配置
shutil.copy2(os.path.join(FD, "tools", "auto_fill_form_tools.py"), os.path.join(BASE, "mcp-form-fill", "tools"))
shutil.copy2(os.path.join(SP, "tools", "file_tools.py"), os.path.join(BASE, "mcp-form-fill", "tools"))
shutil.copy2(os.path.join(FD, "config", "field_synonyms.json"), os.path.join(BASE, "mcp-form-fill", "config"))

# office-word：Word 创作 + 通用文件9
shutil.copy2(os.path.join(FD, "tools", "word_tools.py"), os.path.join(BASE, "mcp-office-word", "tools"))
shutil.copy2(os.path.join(FD, "tools", "file_tools.py"), os.path.join(BASE, "mcp-office-word", "tools"))

# office-excel：CRUD（截取） + csv + 文件传输3
shutil.copy2(os.path.join(SP, "tools", "csv_tools.py"), os.path.join(BASE, "mcp-office-excel", "tools"))
shutil.copy2(os.path.join(SP, "tools", "file_tools.py"), os.path.join(BASE, "mcp-office-excel", "tools"))

# office-pdf：pdf + 文件传输3
shutil.copy2(os.path.join(SP, "tools", "pdf_tools.py"), os.path.join(BASE, "mcp-office-pdf", "tools"))
shutil.copy2(os.path.join(SP, "tools", "file_tools.py"), os.path.join(BASE, "mcp-office-pdf", "tools"))

# ---------- 3. office-excel：精简版 excel_tools.py（CRUD only） ----------
src = r(os.path.join(SP, "tools", "excel_tools.py")).splitlines(keepends=True)
# 模块级(1-101) + register_excel_tools 头到 excel_add_sheet 结束（864 行）
# 865 行起为智能填表段，去掉；在 register 函数内补收尾 print
crud = "".join(src[:864])
tail = "    print(\"[mcp-office-excel] Excel CRUD 工具已注册\", flush=True)\n"
w(os.path.join(BASE, "mcp-office-excel", "tools", "excel_tools.py"), crud + tail)

# ---------- 4. form-fill：excel_form_tools.py（填表 3 件套自包含） ----------
# 原文件 873 行（import re as _re）~ 1449 行（smart_fill_excel except 结束）即填表段，缩进与函数体一致
form_part = "".join(src[872:1449])

header = '''"""
Excel 智能填表 MCP 工具模块（从 mcp-spreadsheet-pdf 拆分）

提供 parse_excel_form / fill_excel_form / smart_fill_excel 三个智能填表工具。
"""

import os
import json
from mcp.server.fastmcp import FastMCP


def _import_openpyxl():
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        return None


def _import_xlrd():
    try:
        import xlrd
        return xlrd
    except ImportError:
        return None


def _is_xls(path: str) -> bool:
    """判断是否为老版 .xls 格式（xlrd 读取）"""
    return path.lower().endswith('.xls') and not path.lower().endswith('.xlsx')


def _resolve_safe_path(path: str, base_dir: str) -> str:
    """安全路径解析"""
    if os.path.isabs(path):
        if not path.startswith(os.path.abspath(base_dir)):
            raise ValueError(f"路径越权: {path}")
        return path
    return os.path.join(base_dir, path)


def register_excel_form_tools(mcp: FastMCP, base_dir: str = "/data", **kwargs):
    """注册 Excel 智能填表工具（parse_excel_form / fill_excel_form / smart_fill_excel）"""

    server_base_url = kwargs.get("server_base_url", "")

    def _make_download_url(abs_file_path: str) -> str:
        """如果文件在 base_dir 下，生成可下载 URL"""
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
                rel = os.path.relpath(abs_file, abs_base).replace("\\\\", "/")
                return f"{url_base}/download/{rel}"
        except Exception:
            pass
        return ""

'''
footer = '\n    print("[mcp-form-fill] Excel 填表工具已注册", flush=True)\n'
w(os.path.join(BASE, "mcp-form-fill", "tools", "excel_form_tools.py"), header + form_part + footer)

print("setup done")
for name in NEW:
    d = os.path.join(BASE, name)
    print(f"[{name}] {sorted(os.listdir(d))} / tools={sorted(os.listdir(os.path.join(d,'tools')))}")
