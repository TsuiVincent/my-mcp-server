"""
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
                rel = os.path.relpath(abs_file, abs_base).replace("\\", "/")
                return f"{url_base}/download/{rel}"
        except Exception:
            pass
        return ""

    import re as _re

    # 常用字段同义词（对齐 mcp-file-doc 内置同义词的常用子集）
    _EXCEL_FIELD_SYNONYMS = {
        '姓名': '姓名', '名字': '姓名', 'name': '姓名',
        '性别': '性别', 'sex': '性别', 'gender': '性别',
        '联系电话': '联系电话', '电话': '联系电话', '手机': '联系电话', '手机号': '联系电话',
        '手机号码': '联系电话', '联系电话号码': '联系电话', '联系方式': '联系电话', 'phone': '联系电话',
        '出生日期': '出生日期', '出生年月': '出生日期', '出生年月日': '出生日期', '生日': '出生日期',
        '身份证号': '身份证号', '身份证号码': '身份证号', '身份证': '身份证号', '证件号码': '身份证号',
        '证件号': '身份证号', 'id': '身份证号', 'idcard': '身份证号',
        '家庭住址': '家庭住址', '住址': '家庭住址', '地址': '家庭住址', '联系地址': '家庭住址',
        '户籍地址': '户籍地址', 'address': '家庭住址',
        '电子邮箱': '电子邮箱', '邮箱': '电子邮箱', 'email': '电子邮箱', 'e-mail': '电子邮箱',
        '学历': '学历', '文化程度': '学历', 'education': '学历',
        '工作单位': '工作单位', '单位': '工作单位', '工作': '工作单位', 'company': '工作单位',
        '民族': '民族', 'nation': '民族',
        '政治面貌': '政治面貌', '政治身份': '政治面貌',
        '婚姻状况': '婚姻状况', '婚否': '婚姻状况', 'marital': '婚姻状况',
        '籍贯': '籍贯', 'nativeplace': '籍贯',
        '年龄': '年龄', 'age': '年龄',
        '身高': '身高', '体重': '体重',
        '毕业院校': '毕业院校', '学校': '毕业院校', '毕业学校': '毕业院校',
        '专业': '专业', '所学专业': '专业', 'major': '专业',
    }

    def _is_empty_cell(text) -> bool:
        t = (text or '').strip()
        return t == '' or t == '【待补充】'

    def _normalize_field_name(name) -> str:
        return _re.sub(r'[\s：:＿_、/()（）\[\]【】\-]+', '', str(name or '')).lower()

    def _excel_cell_ref(row: int, col: int) -> str:
        from openpyxl.utils import get_column_letter
        return f"{get_column_letter(col)}{row}"

    def _build_excel_merged_map(ws) -> dict:
        """{cell_ref: {"range": "A1:B2", "anchor": bool}}"""
        m = {}
        for rng in ws.merged_cells.ranges:
            rng_str = str(rng)
            anchor = _excel_cell_ref(rng.min_row, rng.min_col)  # 锚点 = 区间左上角
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    ref = _excel_cell_ref(r, c)
                    m[ref] = {"range": rng_str, "anchor": (ref == anchor)}
        return m

    def _build_excel_grid(ws) -> list:
        """逻辑网格：[{row, col, cell_ref, text, is_empty, merged}]，row/col 为 1-based"""
        merged_map = _build_excel_merged_map(ws)
        grid = []
        max_row = max(ws.max_row or 0, 1)
        max_col = max(ws.max_column or 0, 1)
        for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
            for cell in row:
                mm = merged_map.get(cell.coordinate)
                is_merged_part = bool(mm and not mm['anchor'])
                raw = cell.value
                text = '' if raw is None else str(raw)
                grid.append({
                    "row": cell.row,
                    "col": cell.column,
                    "cell_ref": cell.coordinate,
                    "text": text,
                    "is_empty": _is_empty_cell(text) and not is_merged_part,
                    "merged": mm,
                })
        return grid

    def _excel_layout_complexity(ws) -> dict:
        flags = []
        if ws.merged_cells.ranges:
            flags.append('merged_cells')
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and ('____' in str(cell.value) or '＿' in str(cell.value)):
                    flags.append('inline_placeholder')
                    break
            if 'inline_placeholder' in flags:
                break
        if flags:
            return {"confidence": "low", "flags": flags}
        return {"confidence": "high", "flags": []}

    def _infer_excel_field_map(ws, merged_map) -> dict:
        """推断待填格子的字段名（左/上最近非空标签），返回 {(row, col): field_name}"""
        result = {}
        max_row = max(ws.max_row or 0, 1)
        max_col = max(ws.max_column or 0, 1)
        for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
            for cell in row:
                mm = merged_map.get(cell.coordinate)
                if mm and not mm['anchor']:
                    continue  # 合并区非锚点不可写
                raw = cell.value
                text = '' if raw is None else str(raw)
                if not _is_empty_cell(text):
                    continue
                label = None
                # 左邻居
                for c in range(cell.column - 1, 0, -1):
                    lc = ws.cell(row=cell.row, column=c)
                    lt = '' if lc.value is None else str(lc.value)
                    if lt.strip():
                        label = lt.strip()
                        break
                # 上邻居
                if not label and cell.row > 1:
                    for r in range(cell.row - 1, 0, -1):
                        uc = ws.cell(row=r, column=cell.column)
                        ut = '' if uc.value is None else str(uc.value)
                        if ut.strip():
                            label = ut.strip()
                            break
                if label:
                    result[(cell.row, cell.column)] = label
        return result

    def _coerce_excel_value(value):
        """数字自动识别：纯数字（<11位）转 int，浮点转 float，其余保留字符串（防手机号/身份证科学计数）"""
        v = str(value)
        if v == '':
            return ''
        stripped = v.strip()
        if stripped.lstrip('-').isdigit() and len(stripped.lstrip('-')) < 11:
            try:
                return int(stripped)
            except ValueError:
                pass
        if stripped.lstrip('-').replace('.', '', 1).isdigit() and '.' in stripped:
            try:
                return float(stripped)
            except ValueError:
                pass
        return v

    def _resolve_anchor(ws, row, col, merged_map):
        """合并区内的坐标解析到锚点（top-left），返回 (r, c)"""
        ref = _excel_cell_ref(row, col)
        mm = merged_map.get(ref)
        if mm and not mm['anchor']:
            for rng in ws.merged_cells.ranges:
                if str(rng) == mm['range']:
                    return rng.min_row, rng.min_col
        return row, col

    def _match_excel_field(text: str, fill_map: dict, normalized_map: dict):
        """字段名匹配：精确 → 规范化 → 同义词 → 分词 → 包含（与 Word 版同构）"""
        t = (text or '').strip()
        if t in fill_map:
            return fill_map[t]
        norm = _normalize_field_name(t)
        if norm in normalized_map:
            return normalized_map[norm]
        if norm in _EXCEL_FIELD_SYNONYMS:
            std = _EXCEL_FIELD_SYNONYMS[norm]
            for key, val in fill_map.items():
                if _normalize_field_name(key) == std:
                    return val
        parts = _re.split(r'[\s/\\|（）()【】\[\]、,\-_.]+', t)
        for part in parts:
            p = part.strip()
            if not p:
                continue
            if p in fill_map:
                return fill_map[p]
            pn = _normalize_field_name(p)
            if pn in normalized_map:
                return normalized_map[pn]
            if pn in _EXCEL_FIELD_SYNONYMS:
                std = _EXCEL_FIELD_SYNONYMS[pn]
                for key, val in fill_map.items():
                    if _normalize_field_name(key) == std:
                        return val
        for key, val in fill_map.items():
            nk = _normalize_field_name(key)
            if nk in norm or norm in nk:
                return val
        return None

    def _extract_knowledge_fill_data(knowledge_data: str) -> dict:
        """从 knowledge_data（JSON 或自然语言）提取 {字段名: 值}"""
        if not knowledge_data:
            return {}
        s = str(knowledge_data).strip()
        if not s:
            return {}
        if s.startswith('{'):
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                flat = {}
                for k, v in data.items():
                    if isinstance(v, dict):
                        for k2, v2 in v.items():
                            if v2 not in (None, '', '【待补充】'):
                                flat[k2] = v2
                    elif isinstance(v, (str, int, float)) and v not in ('', '【待补充】'):
                        flat[k] = v
                return flat
        pairs = _re.findall(r'([\u4e00-\u9fa5A-Za-z]{2,12})[：:]\s*([^\s，,；;]+)', s)
        if pairs:
            return {k.strip(): v.strip() for k, v in pairs}
        return {}

    def _fill_excel_sheet(wb, ws, fill_map, cells_to_fill, merged_map, verbose):
        """在单个工作表上执行填充，返回 (filled_count, fill_details, used_names)"""
        filled_count = 0
        fill_details = []
        used_names = set()
        normalized_map = {}
        for fn, val in fill_map.items():
            normalized_map[_normalize_field_name(fn)] = val
            normalized_map[fn] = val
        # 本次填充过的坐标与值：用于标签推断时跳过已填格（防刚填入的值被当成字段标签）
        filled_coords = set()
        filled_values = set()

        def _do_write(r, c, val, field, src):
            nonlocal filled_count
            ar, ac = _resolve_anchor(ws, r, c, merged_map)
            cell = ws.cell(row=ar, column=ac)
            text = '' if cell.value is None else str(cell.value)
            # ① 标签+下划线同格（"姓名：____"）：就地替换下划线、保留标签（覆盖坐标填充路径）
            if text and ('____' in text or '＿' in text):
                label_part = _re.split(r'[_＿]+', text, 1)[0]
                new_text = _re.sub(r'[_＿]+', str(val), text, count=1)
                cell.value = new_text
                filled_count += 1
                used_names.add((field or label_part).strip())
                filled_coords.add((ar, ac))
                filled_values.add(str(val))
                fill_details.append({"field": (field or label_part).strip(), "value": val,
                                     "cell_ref": _excel_cell_ref(ar, ac), "status": "filled_inline", "source": src})
                return
            # 合并区锚点已有值则跳过（防覆盖表头/已有内容）
            if cell.value not in (None, ''):
                fill_details.append({"field": field, "value": val,
                                     "cell_ref": _excel_cell_ref(r, c), "status": "skipped_non_empty"})
                return
            cell.value = _coerce_excel_value(val)
            filled_count += 1
            used_names.add(field)
            filled_coords.add((ar, ac))
            filled_values.add(str(val))
            fill_details.append({"field": field, "value": val,
                                 "cell_ref": _excel_cell_ref(ar, ac), "status": "filled", "source": src})

        def _is_filled_cell(r, c, cell_value_text):
            """该格是否刚被本次填充（跳过作为标签候选）"""
            if (r, c) in filled_coords:
                return True
            return cell_value_text.strip() in filled_values

        max_row = max(ws.max_row or 0, 1)
        max_col = max(ws.max_column or 0, 1)
        for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
            for cell in row:
                mm = merged_map.get(cell.coordinate)
                if mm and not mm['anchor']:
                    continue
                raw = cell.value
                text = '' if raw is None else str(raw)

                # ① 标签+下划线同格（"姓名：____"）
                if not _is_empty_cell(text) and ('____' in text or '＿' in text):
                    label_part = _re.split(r'[_＿]+', text, 1)[0]
                    val = _match_excel_field(label_part, fill_map, normalized_map)
                    if val is not None:
                        new_text = _re.sub(r'[_＿]+', str(val), text, count=1)
                        cell.value = new_text
                        filled_count += 1
                        used_names.add(label_part.strip())
                        filled_coords.add((cell.row, cell.column))
                        filled_values.add(str(val))
                        fill_details.append({"field": label_part.strip(), "value": val,
                                             "cell_ref": cell.coordinate, "status": "filled_inline"})
                    continue

                # ② 纯空单元格 → 左/上最近标签推断（跳过刚填充的格/值）
                if not _is_empty_cell(text):
                    continue
                label = None
                for c in range(cell.column - 1, 0, -1):
                    lc = ws.cell(row=cell.row, column=c)
                    lt = '' if lc.value is None else str(lc.value)
                    if lt.strip():
                        if not _is_filled_cell(cell.row, c, lt):
                            label = lt.strip()
                        break  # 遇到最近的单元格即停（已填则视为无标签，转向上方）
                if not label and cell.row > 1:
                    for r in range(cell.row - 1, 0, -1):
                        uc = ws.cell(row=r, column=cell.column)
                        ut = '' if uc.value is None else str(uc.value)
                        if ut.strip():
                            if not _is_filled_cell(r, cell.column, ut):
                                label = ut.strip()
                            break
                if not label:
                    continue
                val = _match_excel_field(label, fill_map, normalized_map)
                if val is not None:
                    _do_write(cell.row, cell.column, val, label, 'auto_label')

        # ③ 坐标精确填充（fill_cells_json）
        for item in cells_to_fill:
            if not isinstance(item, dict):
                continue
            try:
                r = int(item.get('row', 0))
                c = int(item.get('col', 0))
            except (ValueError, TypeError):
                r, c = 0, 0
            ref = item.get('cell_ref', '')
            val = str(item.get('value', ''))
            field = item.get('field') or ref or f"r{r}c{c}"
            if val == '':
                fill_details.append({"field": field, "value": val, "cell_ref": ref or _excel_cell_ref(r, c),
                                     "status": "skipped_empty_value"})
                continue
            if ref:
                try:
                    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
                    col_letter, row_num = coordinate_from_string(ref)
                    r, c = row_num, column_index_from_string(col_letter)
                except Exception:
                    pass
            if r < 1 or c < 1:
                fill_details.append({"field": field, "value": val, "cell_ref": ref or f"r{r}c{c}",
                                     "status": "skipped_invalid_coord"})
                continue
            _do_write(r, c, val, field, 'cell_coord')

        return filled_count, fill_details, used_names

    @mcp.tool()
    async def parse_excel_form(path: str, sheet_name: str = "") -> str:
        """解析 Excel 表单结构，识别待填字段与布局复杂度（智能填表第一步）。

Args:
    path: Excel 文件路径（.xlsx/.xlsm，绝对路径或相对路径）
    sheet_name: 工作表名，不填则解析第一个工作表

Returns:
    JSON，包含 fields（推断的待填字段）、tables（逻辑网格，含 cell_ref/合并信息）、
    layout（confidence: high/low + flags）、merged_ranges。
"""
        try:
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)
            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "暂不支持 .xls 旧版格式，请另存为 .xlsx 后上传"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(target)
            try:
                ws = wb[sheet_name] if sheet_name else wb.active
            except KeyError:
                return json.dumps({"error": f"工作表不存在: {sheet_name}"}, ensure_ascii=False)

            merged_map = _build_excel_merged_map(ws)
            grid = _build_excel_grid(ws)
            layout = _excel_layout_complexity(ws)
            inferred = _infer_excel_field_map(ws, merged_map)
            fields = [{
                "field_name": label,
                "row": r, "col": c,
                "cell_ref": _excel_cell_ref(r, c),
                "sheet_name": ws.title,
            } for (r, c), label in sorted(inferred.items(), key=lambda x: (x[0][0], x[0][1]))]

            merged_ranges = [str(rng) for rng in ws.merged_cells.ranges]
            wb.close()

            return json.dumps({
                "status": "ok",
                "file": path,
                "sheet_name": ws.title,
                "fields": fields,
                "tables": [grid],
                "layout": layout,
                "merged_ranges": merged_ranges,
                "usage": "布局 high → 可直接用 smart_fill_excel 自动填；low → 读 tables 网格，"
                         "输出 fill_cells_json 坐标映射后调用 fill_excel_form。",
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def fill_excel_form(
        path: str,
        output_file: str,
        fill_data_json: str = "[]",
        fill_cells_json: str = "",
        sheet_name: str = "",
        verbose: bool = False,
    ) -> str:
        """按字段/坐标填充 Excel 表单，保留原单元格样式（智能填表第二步）。

Args:
    path: 待填 Excel 文件路径（.xlsx/.xlsm）
    output_file: 输出文件名（如 "已填写.xlsx"），保存到服务器 uploads/ 目录
    fill_data_json: 填充数据 JSON，如 [{"field_name": "姓名", "value": "张三"}]
    fill_cells_json: 坐标映射 JSON（异形表推荐），如
        [{"cell_ref": "B3", "value": "张三", "field": "姓名"},
         {"row": 4, "col": 2, "value": "男", "field": "性别"}]
        row/col 为 1-based；合并单元格自动解析到锚点（左上角）
    sheet_name: 工作表名，不填则默认第一个
    verbose: 是否返回详细填充信息

Returns:
    JSON，包含 output_path、output_link、filled_count 等
"""
        try:
            from datetime import datetime
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)
            safe_input = _resolve_safe_path(path, base_dir)
            if not os.path.exists(safe_input):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持写入 .xls 格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            timestamp = datetime.now().strftime("%Y%m%d%H%M")
            base_out, ext = os.path.splitext(os.path.basename(output_file))
            if ext.lower() not in ('.xlsx', '.xlsm'):
                ext = '.xlsx'
            abs_output = os.path.join(base_dir, "uploads", f"{base_out}_{timestamp}{ext}")

            fill_data = json.loads(fill_data_json)
            if not isinstance(fill_data, list):
                return json.dumps({"error": "fill_data_json 必须是 JSON 数组"}, ensure_ascii=False)
            fill_map = {}
            for f in fill_data:
                if isinstance(f, dict) and f.get('field_name') and f.get('value') not in (None, ''):
                    fill_map[str(f['field_name'])] = str(f['value'])

            cells_to_fill = []
            if fill_cells_json and str(fill_cells_json).strip():
                try:
                    cells_to_fill = json.loads(fill_cells_json)
                except json.JSONDecodeError:
                    return json.dumps({"error": "fill_cells_json 必须是合法 JSON 数组"}, ensure_ascii=False)
                if not isinstance(cells_to_fill, list):
                    return json.dumps({"error": "fill_cells_json 必须是数组"}, ensure_ascii=False)

            wb = openpyxl.load_workbook(safe_input)
            try:
                ws = wb[sheet_name] if sheet_name else wb.active
            except KeyError:
                wb.close()
                return json.dumps({"error": f"工作表不存在: {sheet_name}"}, ensure_ascii=False)

            merged_map = _build_excel_merged_map(ws)
            filled_count, fill_details, used_names = _fill_excel_sheet(
                wb, ws, fill_map, cells_to_fill, merged_map, verbose)

            unmatched = [{"field_name": fn, "value": v} for fn, v in fill_map.items() if fn not in used_names]

            os.makedirs(os.path.dirname(abs_output), exist_ok=True)
            wb.save(abs_output)
            wb.close()

            result = {
                "status": "ok",
                "output_path": abs_output,
                "output_link": _make_download_url(abs_output),
                "filled_count": filled_count,
                "total_fields": len(fill_map),
                "sheet_name": ws.title,
                "output_file": os.path.basename(abs_output),
            }
            if verbose:
                result["fill_details"] = fill_details
                result["unmatched_fields"] = unmatched
            else:
                result["unmatched_field_names"] = [u["field_name"] for u in unmatched]
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool()
    async def smart_fill_excel(
        path: str,
        knowledge_data: str = "",
        fill_data_json: str = "[]",
        output_file: str = "",
        sheet_name: str = "",
        verbose: bool = False,
    ) -> str:
        """一站式智能填表（Excel）：从知识库/数据自动推断并填充，保留样式。

Args:
    path: 服务器上的 Excel 文件路径，如 "/data/uploads/报名表.xlsx"
    knowledge_data: 知识库检索结果（JSON 或自然语言），优先级最高
    fill_data_json: 显式填充数据，如 [{"field_name": "姓名", "value": "张三"}]；
                    未提供时自动从 knowledge_data 提取
    output_file: 输出文件名（默认 "已填写.xlsx"）
    sheet_name: 工作表名，不填则默认第一个
    verbose: 是否返回详细填充信息

Returns:
    JSON，包含 output_path、output_link、filled_count、unmatched_field_names
"""
        try:
            from datetime import datetime
            openpyxl = _import_openpyxl()
            if openpyxl is None:
                return json.dumps({"error": "openpyxl 未安装"}, ensure_ascii=False)
            safe_input = _resolve_safe_path(path, base_dir)
            if not os.path.exists(safe_input):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
            if _is_xls(path):
                return json.dumps({"error": "不支持 .xls 旧版格式，请使用 .xlsx 格式"}, ensure_ascii=False)

            # 合并数据：knowledge_data 优先，fill_data_json 兜底
            fill_map = {}
            if knowledge_data and str(knowledge_data).strip():
                fill_map.update(_extract_knowledge_fill_data(knowledge_data))
            if fill_data_json and str(fill_data_json).strip():
                try:
                    fd = json.loads(fill_data_json)
                except json.JSONDecodeError:
                    fd = []
                if isinstance(fd, list):
                    for f in fd:
                        if isinstance(f, dict) and f.get('field_name') and f.get('value') not in (None, ''):
                            fill_map[str(f['field_name'])] = str(f['value'])

            timestamp = datetime.now().strftime("%Y%m%d%H%M")
            out_name = (output_file or "已填写.xlsx").strip()
            if not out_name.lower().endswith(('.xlsx', '.xlsm')):
                out_name = out_name + ".xlsx"
            base_out, ext = os.path.splitext(os.path.basename(out_name))
            abs_output = os.path.join(base_dir, "uploads", f"{base_out}_{timestamp}{ext}")

            wb = openpyxl.load_workbook(safe_input)
            try:
                ws = wb[sheet_name] if sheet_name else wb.active
            except KeyError:
                wb.close()
                return json.dumps({"error": f"工作表不存在: {sheet_name}"}, ensure_ascii=False)

            merged_map = _build_excel_merged_map(ws)
            filled_count, fill_details, used_names = _fill_excel_sheet(
                wb, ws, fill_map, [], merged_map, verbose)
            unmatched = [{"field_name": fn, "value": v} for fn, v in fill_map.items() if fn not in used_names]

            os.makedirs(os.path.dirname(abs_output), exist_ok=True)
            wb.save(abs_output)
            wb.close()

            result = {
                "status": "ok",
                "output_path": abs_output,
                "output_link": _make_download_url(abs_output),
                "filled_count": filled_count,
                "total_fields": len(fill_map),
                "sheet_name": ws.title,
                "output_file": os.path.basename(abs_output),
            }
            if verbose:
                result["fill_details"] = fill_details
                result["unmatched_fields"] = unmatched
            else:
                result["unmatched_field_names"] = [u["field_name"] for u in unmatched]
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    print("[mcp-form-fill] Excel 填表工具已注册", flush=True)
