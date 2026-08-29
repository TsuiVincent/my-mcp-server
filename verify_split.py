# -*- coding: utf-8 -*-
"""校验拆分后的模块：语法 + 工具注册清单"""
import py_compile
import re
import sys

files = [
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-office-excel\tools\excel_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-form-fill\tools\excel_form_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-form-fill\tools\auto_fill_form_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-office-word\tools\word_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-office-word\tools\file_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-office-excel\tools\csv_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-office-pdf\tools\pdf_tools.py",
    r"e:\Python_Project\work_plication\my-mcp-server\mcp-form-fill\tools\file_tools.py",
]

for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print("OK   ", f.split("my-mcp-server")[-1])
    except Exception as e:
        print("FAIL ", f, "->", e)

def tools_of(path):
    src = open(path, encoding="utf-8").read()
    return re.findall(r"async def (\w+)\(", src)

print("\n--- mcp-office-excel/excel_tools.py ---")
print(tools_of(files[0]))
print("\n--- mcp-form-fill/excel_form_tools.py ---")
print(tools_of(files[1]))
