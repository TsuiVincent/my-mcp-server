# -*- coding: utf-8 -*-
"""复制字体与 __init__.py 到拆分后的新服务"""
import os
import shutil

BASE = r"e:\Python_Project\work_plication\my-mcp-server"
SP = os.path.join(BASE, "mcp-spreadsheet-pdf")
FONT = os.path.join(SP, "方正小标宋简.TTF")

for d in ["mcp-form-fill", "mcp-office-excel", "mcp-office-pdf"]:
    shutil.copy2(FONT, os.path.join(BASE, d, "方正小标宋简.TTF"))

for d in ["mcp-form-fill", "mcp-office-word", "mcp-office-excel", "mcp-office-pdf"]:
    init = os.path.join(BASE, d, "tools", "__init__.py")
    with open(init, "w", encoding="utf-8") as f:
        f.write("# mcp tools package\n")

print("fonts + __init__.py copied")
