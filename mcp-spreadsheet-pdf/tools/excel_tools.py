"""
Excel 操作 MCP 工具模块

提供完整的 Excel 读写编辑能力。
写操作基于 openpyxl，支持 .xlsx / .xlsm / .xltx / .xltm。
读操作兼容 .xls（通过 xlrd）。

工具列表:
- excel_create         创建新工作簿
- excel_read           读取工作表数据
- excel_get_sheets     获取工作簿中的工作表列表
- excel_write_cell     写入单元格
- excel_write_row      写入一行数据
- excel_write_data     写入结构化数据（列表/字典）
- excel_insert_rows    插入行
- excel_delete_rows    删除行
- excel_merge_cells    合并单元格
- excel_set_column_width 设置列宽
- excel_set_cell_style 设置单元格样式
"""

import os
import json
from mcp.server.fastmcp import FastMCP

# openpyxl 已在 requirements.txt 中依赖


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


def _parse_cell_ref(cell_ref: str):
    """将 "A1" 格式的单元格引用解析为 (row, col)，均为 1-based。

    用于 xlrd 路径，因为 xlrd 不提供 coordinate_to_tuple。
    """
    col_str = ''
    row_str = ''
    for ch in cell_ref.upper():
        if ch.isalpha():
            col_str += ch
        else:
            row_str += ch
    col = 0
    for ch in col_str:
        col = col * 26 + (ord(ch) - ord('A') + 1)
    return int(row_str) if row_str else 1, col


def _resolve_safe_path(path: str, base_dir: str) -> str:
    """安全路径解析"""
    if os.path.isabs(path):
        if not path.startswith(os.path.abspath(base_dir)):
            raise ValueError(f"路径越权: {path}")
        return path
    return os.path.join(base_dir, path)


def _parse_color(color_str: str) -> str:
    """解析颜色字符串为 rrggbb 格式"""
    color_map = {
        '黑色': '000000', '黑': '000000',
        '红色': 'FF0000', '红': 'FF0000',
        '绿色': '00FF00', '绿': '00FF00',
        '蓝色': '0000FF', '蓝': '0000FF',
        '白色': 'FFFFFF', '白': 'FFFFFF',
        '灰色': '808080', '灰': '808080',
        '黄色': 'FFFF00', '黄': 'FFFF00',
        '橙色': 'FFA500', '橙': 'FFA500',
        '紫色': '800080', '紫': '800080',
        '粉色': 'FFC0CB', '粉': 'FFC0CB',
    }
    color_lower = color_str.strip().lower()
    if color_lower in color_map:
        return color_map[color_lower]
    # 如果是十六进制 (带或不带 #)
    hex_str = color_str.lstrip('#').upper()
    if len(hex_str) == 6:
        return hex_str
    if len(hex_str) == 8:
        return hex_str
    return '000000'  # 默认黑色


def register_excel_tools(mcp: FastMCP, base_dir: str = "/data", **kwargs):
    """注册 Excel 操作工具"""

    # ==========================================
    # 创建
    # ==========================================

    @mcp.tool()
    async def excel_create(filename: str, sheet_name: str = "Sheet1") -> str:
        """创建新的 Excel 工作簿。

        Args:
            filename: 文件名（如 "report.xlsx"），保存在 uploads/ 目录
            sheet_name: 工作表名，默认 "Sheet1"

        Returns:
            JSON，包含 output_path、download_url（Docker 环境有）和 sheet_count
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装。请执行: pip install openpyxl"}, ensure_ascii=False)

            target = _resolve_safe_path(filename, base_dir)
            os.makedirs(os.path.dirname(target), exist_ok=True)

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = sheet_name
            wb.save(target)

            result = {
                "status": "ok",
                "output_path": target,
                "filename": filename,
                "sheet_count": 1,
                "sheets": [sheet_name],
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 读取
    # ==========================================

    @mcp.tool()
    async def excel_read(
        path: str,
        sheet_name: str = "",
        start_cell: str = "A1",
        end_cell: str = "",
        max_rows: int = 500,
    ) -> str:
        """读取 Excel 工作表数据。

        Args:
            path: Excel 文件路径（绝对路径或相对路径）
            sheet_name: 工作表名，不填则默认读取第一个工作表
            start_cell: 起始单元格，默认 "A1"
            end_cell: 结束单元格（如 "G20"），不填则读取到数据末尾
            max_rows: 最大读取行数，默认 500（防大文件卡死）

        Returns:
            JSON，包含 sheet_name、row_count、column_count、headers（首行）、data（二维数组）
        """
        try:
            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            # ===== .xls 路径 (xlrd) =====
            if _is_xls(path):
                xlrd = _import_xlrd()
                if xlrd is None:
                    return json.dumps({"error": "读取 .xls 需要 xlrd。请执行: pip install xlrd"}, ensure_ascii=False)

                start_row, start_col = _parse_cell_ref(start_cell)
                end_row_parsed, end_col_parsed = None, None
                if end_cell:
                    end_row_parsed, end_col_parsed = _parse_cell_ref(end_cell)

                wb = xlrd.open_workbook(target)
                if sheet_name:
                    try:
                        ws = wb.sheet_by_name(sheet_name)
                    except xlrd.XLRDError:
                        return json.dumps({"error": f"工作表不存在: {sheet_name}"}, ensure_ascii=False)
                else:
                    ws = wb.sheet_by_index(0)

                end_row = end_row_parsed or min(start_row + max_rows, ws.nrows + 1)
                end_col_final = end_col_parsed or ws.ncols

                data = []
                row_count = 0
                for ri in range(start_row - 1, min(end_row - 1, ws.nrows)):
                    row_data = []
                    for ci in range(start_col - 1, min(end_col_final - 1, ws.ncols)):
                        cell = ws.cell(ri, ci)
                        row_data.append(str(cell.value) if cell.value != '' else '')
                    data.append(row_data)
                    row_count += 1
                    if row_count >= max_rows:
                        break

                result = {
                    "status": "ok",
                    "file": path,
                    "format": "xls",
                    "sheet_name": ws.name,
                    "row_count": row_count,
                    "column_count": len(data[0]) if data else 0,
                    "dimensions": f"A1:{chr(64 + ws.ncols)}{ws.nrows}" if ws.ncols <= 26 else f"{ws.nrows}x{ws.ncols}",
                    "headers": data[0] if data else [],
                    "data": data,
                }
                return json.dumps(result, ensure_ascii=False, indent=2)

            # ===== .xlsx 路径 (openpyxl) =====
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target, read_only=True, data_only=True)
            ws = wb[sheet_name] if sheet_name else wb.active
            if ws is None:
                return json.dumps({"error": f"工作表不存在: {sheet_name or '(默认)'}"}, ensure_ascii=False)

            # 解析起始单元格
            from openpyxl.utils import coordinate_to_tuple
            start_row, start_col = coordinate_to_tuple(start_cell)
            end_row, end_col = None, None
            if end_cell:
                end_row, end_col = coordinate_to_tuple(end_cell)

            data = []
            row_count = 0
            for row in ws.iter_rows(
                min_row=start_row, max_row=end_row or start_row + max_rows - 1,
                min_col=start_col, max_col=end_col or ws.max_column,
                values_only=True
            ):
                data.append([str(v) if v is not None else "" for v in row])
                row_count += 1
                if row_count >= max_rows:
                    break

            wb.close()

            result = {
                "status": "ok",
                "file": path,
                "format": "xlsx",
                "sheet_name": ws.title,
                "row_count": row_count,
                "column_count": len(data[0]) if data else 0,
                "dimensions": f"{ws.dimensions}",
                "headers": data[0] if data else [],
                "data": data,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_get_sheets(path: str) -> str:
        """获取 Excel 工作簿中的所有工作表名称及基本信息。

        Args:
            path: Excel 文件路径

        Returns:
            JSON，包含工作表列表，每个含 name、max_row、max_column、dimensions
        """
        try:
            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            # ===== .xls 路径 (xlrd) =====
            if _is_xls(path):
                xlrd = _import_xlrd()
                if xlrd is None:
                    return json.dumps({"error": "读取 .xls 需要 xlrd。请执行: pip install xlrd"}, ensure_ascii=False)

                wb = xlrd.open_workbook(target)
                sheets = []
                for idx, name in enumerate(wb.sheet_names()):
                    ws = wb.sheet_by_index(idx)
                    sheets.append({
                        "name": name,
                        "max_row": ws.nrows,
                        "max_column": ws.ncols,
                        "dimensions": f"{ws.nrows} 行 x {ws.ncols} 列",
                    })

                return json.dumps({
                    "status": "ok",
                    "file": path,
                    "format": "xls",
                    "sheet_count": len(sheets),
                    "sheets": sheets,
                }, ensure_ascii=False, indent=2)

            # ===== .xlsx 路径 (openpyxl) =====
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target, read_only=True, data_only=True)
            sheets = []
            for name in wb.sheetnames:
                ws = wb[name]
                sheets.append({
                    "name": name,
                    "max_row": ws.max_row,
                    "max_column": ws.max_column,
                    "dimensions": str(ws.dimensions),
                })
            wb.close()

            return json.dumps({
                "status": "ok",
                "file": path,
                "format": "xlsx",
                "sheet_count": len(sheets),
                "sheets": sheets,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 写入
    # ==========================================

    @mcp.tool()
    async def excel_write_cell(
        path: str,
        cell: str,
        value: str,
        sheet_name: str = "",
    ) -> str:
        """向指定单元格写入数据。

        Args:
            path: Excel 文件路径
            cell: 单元格位置（如 "B3"、"A1"）
            value: 要写入的值（数字会自动识别）
            sheet_name: 工作表名，不填则默认第一个

        Returns:
            JSON，包含 success、cell、value、sheet_name
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active
            if ws is None:
                return json.dumps({"error": "工作表不存在"}, ensure_ascii=False)

            # 自动识别数字
            try:
                if '.' in value:
                    ws[cell] = float(value)
                else:
                    ws[cell] = int(value)
            except (ValueError, TypeError):
                ws[cell] = value

            wb.save(target)

            return json.dumps({
                "status": "ok",
                "cell": cell,
                "value": value,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_write_row(
        path: str,
        start_cell: str,
        values: str,
        sheet_name: str = "",
    ) -> str:
        """向工作表中写入一行数据。

        Args:
            path: Excel 文件路径
            start_cell: 起始单元格（如 "A3"）
            values: JSON 数组字符串，如 '["姓名","年龄","性别"]'
            sheet_name: 工作表名，不填则默认第一个

        Returns:
            JSON，包含 success、cells_written
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            vals = json.loads(values)
            if not isinstance(vals, list):
                return json.dumps({"error": "values 必须是 JSON 数组"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active

            from openpyxl.utils import coordinate_to_tuple
            row, col = coordinate_to_tuple(start_cell)

            for i, v in enumerate(vals):
                cell = ws.cell(row=row, column=col + i)
                try:
                    if isinstance(v, str):
                        stripped = v.strip()
                        if stripped.lstrip('-').isdigit():
                            cell.value = int(stripped)
                        elif stripped.replace('.', '', 1).lstrip('-').isdigit():
                            cell.value = float(stripped)
                        else:
                            cell.value = v
                    elif isinstance(v, (int, float)):
                        cell.value = v
                    else:
                        cell.value = str(v)
                except Exception:
                    cell.value = str(v)

            wb.save(target)

            return json.dumps({
                "status": "ok",
                "start_cell": start_cell,
                "cells_written": len(vals),
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_write_data(
        path: str,
        data: str,
        start_cell: str = "A1",
        sheet_name: str = "",
        with_headers: bool = True,
    ) -> str:
        """将结构化数据批量写入工作表。

        支持两种数据格式:
        1. 列表的列表：[[col1, col2, ...], [col1, col2, ...], ...]
        2. 字典列表：[{key1: val1, key2: val2}, ...] —— with_headers=True 时自动写出表头

        Args:
            path: Excel 文件路径
            data: JSON 字符串，二维数组或字典列表
            start_cell: 起始单元格，默认 A1
            sheet_name: 工作表名
            with_headers: 字典列表时是否输出表头行，默认 True

        Returns:
            JSON，包含 rows_written、cols_written
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            parsed = json.loads(data)
            if not isinstance(parsed, list) or len(parsed) == 0:
                return json.dumps({"error": "data 必须是非空 JSON 数组"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active

            from openpyxl.utils import coordinate_to_tuple
            start_row, start_col = coordinate_to_tuple(start_cell)

            # 判断是字典列表还是列表的列表
            if isinstance(parsed[0], dict):
                # 字典列表
                keys = list(parsed[0].keys())
                if with_headers:
                    for ci, key in enumerate(keys):
                        ws.cell(row=start_row, column=start_col + ci, value=key)
                    data_start_row = start_row + 1
                else:
                    data_start_row = start_row

                for ri, item in enumerate(parsed):
                    for ci, key in enumerate(keys):
                        v = item.get(key, "")
                        ws.cell(row=data_start_row + ri, column=start_col + ci, value=v if v is not None else "")
                rows_written = (data_start_row - start_row) + len(parsed)
                cols_written = len(keys)
            else:
                # 列表的列表
                for ri, row_data in enumerate(parsed):
                    if isinstance(row_data, list):
                        for ci, v in enumerate(row_data):
                            ws.cell(row=start_row + ri, column=start_col + ci, value=v if v is not None else "")
                    else:
                        # 单行数据
                        ws.cell(row=start_row + ri, column=start_col, value=row_data if row_data is not None else "")
                rows_written = len(parsed)
                cols_written = max((len(r) if isinstance(r, list) else 1) for r in parsed)

            wb.save(target)

            return json.dumps({
                "status": "ok",
                "rows_written": rows_written,
                "cols_written": cols_written,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 编辑
    # ==========================================

    @mcp.tool()
    async def excel_insert_rows(
        path: str,
        row_index: int,
        count: int = 1,
        sheet_name: str = "",
    ) -> str:
        """在指定位置插入空行。

        Args:
            path: Excel 文件路径
            row_index: 插入位置的行号（从 1 开始），在此行之前插入
            count: 插入行数，默认 1
            sheet_name: 工作表名

        Returns:
            JSON，包含 success、inserted_at、count
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active
            ws.insert_rows(row_index, amount=count)
            wb.save(target)

            return json.dumps({
                "status": "ok",
                "inserted_at": row_index,
                "count": count,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_delete_rows(
        path: str,
        row_index: int,
        count: int = 1,
        sheet_name: str = "",
    ) -> str:
        """删除指定位置的行。

        Args:
            path: Excel 文件路径
            row_index: 删除起始行号（从 1 开始）
            count: 删除行数，默认 1
            sheet_name: 工作表名

        Returns:
            JSON，包含 success、deleted_from、count
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active
            ws.delete_rows(row_index, amount=count)
            wb.save(target)

            return json.dumps({
                "status": "ok",
                "deleted_from": row_index,
                "count": count,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_merge_cells(
        path: str,
        cell_range: str,
        sheet_name: str = "",
    ) -> str:
        """合并单元格。

        Args:
            path: Excel 文件路径
            cell_range: 单元格范围（如 "A1:C1" 横向合并，或 "A1:A3" 纵向合并）
            sheet_name: 工作表名

        Returns:
            JSON，包含 success、merged_range
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active
            ws.merge_cells(cell_range)
            wb.save(target)

            return json.dumps({
                "status": "ok",
                "merged_range": cell_range,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_set_column_width(
        path: str,
        col_letter: str,
        width: float = 15,
        sheet_name: str = "",
    ) -> str:
        """设置列宽。

        Args:
            path: Excel 文件路径
            col_letter: 列字母（如 "A", "B", "C"）
            width: 列宽（字符单位），默认 15
            sheet_name: 工作表名

        Returns:
            JSON，包含 success、column、width
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active
            ws.column_dimensions[col_letter.upper()].width = width
            wb.save(target)

            return json.dumps({
                "status": "ok",
                "column": col_letter.upper(),
                "width": width,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_set_cell_style(
        path: str,
        cell_range: str,
        bold: bool = False,
        font_size: float = 11,
        font_color: str = "",
        bg_color: str = "",
        alignment: str = "",
        sheet_name: str = "",
    ) -> str:
        """设置单元格样式：字体、颜色、对齐、背景色。

        Args:
            path: Excel 文件路径
            cell_range: 单元格范围（如 "A1" 或 "A1:D1"）
            bold: 是否加粗，默认 False
            font_size: 字体大小，默认 11
            font_color: 字体颜色（红/蓝/绿/#FF0000 等），不填则不变
            bg_color: 背景填充色，不填则不变
            alignment: 对齐方式（left/center/right），不填则不变
            sheet_name: 工作表名

        Returns:
            JSON，包含 success、styled_range
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            from openpyxl.styles import Font, PatternFill, Alignment

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            ws = wb[sheet_name] if sheet_name else wb.active

            # 构建字体
            font_kwargs = {"bold": bold, "size": font_size}
            if font_color:
                font_kwargs["color"] = _parse_color(font_color)
            font = Font(**font_kwargs)

            # 构建背景填充
            fill = None
            if bg_color:
                fill = PatternFill(start_color=_parse_color(bg_color), end_color=_parse_color(bg_color), fill_type="solid")

            # 构建对齐
            alignment_obj = None
            if alignment:
                align_map = {"left": "left", "center": "center", "right": "right"}
                align_h = align_map.get(alignment.lower(), "center")
                alignment_obj = Alignment(horizontal=align_h, vertical="center")

            # 应用样式到单元格范围
            for row in ws[cell_range]:
                for cell in row:
                    cell.font = font
                    if fill:
                        cell.fill = fill
                    if alignment_obj:
                        cell.alignment = alignment_obj

            wb.save(target)

            return json.dumps({
                "status": "ok",
                "styled_range": cell_range,
                "bold": bold,
                "font_size": font_size,
                "font_color": font_color,
                "bg_color": bg_color,
                "alignment": alignment,
                "sheet_name": ws.title,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def excel_add_sheet(
        path: str,
        sheet_name: str,
    ) -> str:
        """向已有工作簿添加新工作表。

        Args:
            path: Excel 文件路径
            sheet_name: 新工作表名

        Returns:
            JSON，包含 success、sheet_name
        """
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)

            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            wb.create_sheet(title=sheet_name)
            wb.save(target)

            return json.dumps({
                "status": "ok",
                "added_sheet": sheet_name,
                "total_sheets": len(wb.sheetnames),
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    print("[mcp-spreadsheet-pdf] Excel 工具已注册", flush=True)
