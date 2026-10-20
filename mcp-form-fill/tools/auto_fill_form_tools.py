# auto_fill_form_tools.py
"""
自动填表 MCP 工具模块
支持多源个人信息获取：知识库、用户输入文本、上传文件、指定路径文档

使用方式:
    from auto_fill_form_tools import register_auto_fill_tools
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("my-server")
    register_auto_fill_tools(mcp, base_dir="/data")
"""

import os
import sys
import json
import re
import base64
import time
import asyncio
import zipfile
import uuid
from typing import Optional
from mcp.server.fastmcp import FastMCP


# 文件大小限制：最大允许上传的 Word 文件大小（MB）
# Base64 编码后体积约为原始文件的 4/3，故限制 Base64 字符串长度
MAX_FILE_SIZE_MB = 15


def _check_base64_size(file_base64: str, max_mb: int = MAX_FILE_SIZE_MB) -> str | None:
    """检查 Base64 字符串大小是否超限。返回错误信息或 None（通过）。"""
    max_len = int(max_mb * 1024 * 1024 * 4 / 3)
    if len(file_base64) > max_len:
        approx_mb = round(len(file_base64) * 3 / 4 / 1024 / 1024, 1)
        return (
            f"文件过大（约 {approx_mb} MB）。"
            f"最大允许 {max_mb} MB。"
            f"建议：压缩图片后重新上传，或使用本地路径方式填写。"
        )
    return None


def _validate_docx_file(path: str) -> str | None:
    """验证文件是否为有效的 .docx（ZIP 包）。返回错误信息或 None（通过）。"""
    if not os.path.exists(path):
        return f"文件不存在: {path}"
    size = os.path.getsize(path)
    if size == 0:
        return f"文件为空（0 字节）: {path}。请检查上传内容是否完整。"
    if not zipfile.is_zipfile(path):
        return (
            f"文件不是有效的 .docx 格式（大小 {size} 字节）。"
            f"可能原因：1) 旧版 .doc 格式（需另存为 .docx）；2) 文件上传不完整或已损坏；"
            f"3) 文件内容被截断。路径: {path}"
        )
    return None


# 空白占位符集合，用于判断单元格是否为待填写
EMPTY_PLACEHOLDERS = {'', ' ', '____', '________', '—', '--', '□', '〇', '/'}

# 常见占位文本（中文表单中常见的"请填写"类提示）
PLACEHOLDER_PATTERNS = [
    r'^请填写$',
    r'^请输入$',
    r'^（请填写）$',
    r'^\(请填写\)$',
    r'^请选择$',
    r'^待填写$',
    r'^待补充$',
    r'^无$',
    r'^/$',           # 单独一个斜杠
    r'^\\$',
]

# 内置默认同义词映射（当外部配置文件不可用时使用）
_DEFAULT_FIELD_SYNONYMS = {
    '出生年月': '出生日期',
    '出生日期': '出生日期',
    '出生时间': '出生日期',
    '政治面貌': '政治面貌',
    '党派': '政治面貌',
    '入党时间': '入党日期',
    '学历': '最高学历',
    '最高学历': '最高学历',
    '文化程度': '最高学历',
    '学位': '最高学历',
    '联系电话': '手机号码',
    '手机号码': '手机号码',
    '手机号': '手机号码',
    '手机': '手机号码',
    '电话号码': '手机号码',
    '联系方式': '手机号码',
    '电子邮箱': '电子邮箱',
    '邮箱': '电子邮箱',
    '邮件': '电子邮箱',
    '现居住地址': '家庭住址',
    '现居地址': '家庭住址',
    '家庭住址': '家庭住址',
    '通讯地址': '家庭住址',
    '住址': '家庭住址',
    '地址': '家庭住址',
    '配偶姓名': '配偶',
    '子女姓名': '子女',
    '配偶身份证号': '配偶身份证号',
    '子女身份证号': '子女身份证号',
    '军官证号': '军官证',
    '军士证号': '军士证',
    '文职证号': '文职证',
    '工作单位': '现工作单位',
    '所在单位': '现工作单位',
    '单位名称': '现工作单位',
    '公司': '现工作单位',
    '现工作单位': '现工作单位',
    '职务': '职务',
    '岗位': '职务',
    '职称': '职务',
    '担任职位': '职务',
    '职位': '职务',
    '紧急联系人': '紧急联系人',
    '联系人': '紧急联系人',
    '紧急联系人电话': '紧急联系人电话',
    '联系人电话': '紧急联系人电话',
    '开户行': '开户行',
    '银行名称': '开户行',
    '银行': '开户行',
    '银行卡号': '银行卡号',
    '账号': '银行卡号',
    '卡号': '银行卡号',
    '毕业院校': '毕业院校',
    '学校': '毕业院校',
    '所学专业': '专业',
    '专业': '专业',
    '毕业时间': '毕业时间',
    '姓名': '姓名',
    '性别': '性别',
    '身份证号': '身份证号',
    '证件号码': '身份证号',
    '身份证': '身份证号',
    '民族': '民族',
    '婚姻状况': '婚姻状况',
    '籍贯': '籍贯',
    '健康状况': '健康状况',
    '工作年限': '工作年限',
    '部门': '部门',
    '开户行地址': '开户行地址',
}


def _load_field_synonyms(config_path: str = None, base_dir: str = "/data") -> dict:
    """
    加载字段同义词映射，优先级：参数指定 > 环境变量 > base_dir 下自动发现 > 内置默认

    Args:
        config_path: 直接指定的 JSON 配置文件路径
        base_dir: 数据根目录，自动搜索 config/field_synonyms.json 或 field_synonyms.json

    Returns:
        dict: 同义词映射表
    """
    search_paths = []

    # 1. 参数直接指定
    if config_path:
        search_paths.append(config_path)

    # 2. 环境变量 FIELD_SYNONYMS_CONFIG
    env_path = os.environ.get("FIELD_SYNONYMS_CONFIG")
    if env_path:
        search_paths.append(env_path)

    # 3. base_dir 下自动搜索
    search_paths.append(os.path.join(base_dir, "config", "field_synonyms.json"))
    search_paths.append(os.path.join(base_dir, "field_synonyms.json"))
    # 项目根目录下的 config 目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    search_paths.append(os.path.join(project_root, "config", "field_synonyms.json"))

    for p in search_paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 过滤掉元数据字段（以 _ 开头的 key）
                synonyms = {k: v for k, v in data.items() if not k.startswith('_')}
                if synonyms:
                    print(f"[auto_fill] 已加载同义词配置: {p} ({len(synonyms)} 条)", file=sys.stderr)
                    # 外部配置优先，但内置常用同义词仍作为兜底合并进来，
                    # 避免配置缺项（如 手机号/手机号码）导致同义字段匹配失败
                    merged = dict(_DEFAULT_FIELD_SYNONYMS)
                    merged.update(synonyms)
                    return merged
            except Exception as e:
                print(f"[auto_fill] 加载同义词配置失败 {p}: {e}，使用内置默认", file=sys.stderr)

    print(f"[auto_fill] 未找到外部同义词配置，使用内置默认 ({len(_DEFAULT_FIELD_SYNONYMS)} 条)", file=sys.stderr)
    return dict(_DEFAULT_FIELD_SYNONYMS)


def _is_empty_cell(text: str) -> bool:
    """判断单元格文本是否为空白/待填写状态"""
    text = text.strip()
    if text in EMPTY_PLACEHOLDERS:
        return True
    # 匹配纯下划线、纯空格、纯横线等占位符
    if re.match(r'^[_\s\-—□〇/]+$', text):
        return True
    # 匹配常见占位文本
    for pattern in PLACEHOLDER_PATTERNS:
        if re.match(pattern, text):
            return True
    return False


def _normalize_field_name(name: str) -> str:
    """规范化字段名：去除空格、中英文标点、常见分隔符，统一用于匹配"""
    name = name.strip()
    # 去掉所有空白、中英文冒号、斜杠、括号、顿号、连字符、下划线等常见分隔符
    name = re.sub(r'[\s：:：/\\|（）()【】\[\]、,\-_.~!@#$%^&*+=?<>"\'\`]+', '', name)
    return name


def _search_file(filename: str) -> str | None:
    """在常见目录中搜索文件，返回找到的第一个完整路径"""
    home = os.path.expanduser("~")
    search_dirs = [
        home,
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "mcp-data"),
        os.getcwd(),
    ]

    # Docker 容器内：额外的宿主目录挂载点
    for env_key in ("HOST_DOWNLOADS", "HOST_DESKTOP", "HOST_DOCUMENTS"):
        mp = os.environ.get(env_key, "")
        if mp and os.path.isdir(mp) and mp not in search_dirs:
            search_dirs.append(mp)

    # Cherry Studio 上传文件存储目录
    if os.name == "nt":
        cherry_base = os.path.join(os.environ.get("APPDATA", ""), "CherryStudio", "Data", "Files")
        if os.path.isdir(cherry_base):
            search_dirs.append(cherry_base)
    elif os.name == "posix":
        for cherry_base in [
            os.path.expanduser("~/.config/cherry-studio/Data/Files"),
            os.path.expanduser("~/Library/Application Support/CherryStudio/Data/Files"),
        ]:
            if os.path.isdir(cherry_base):
                search_dirs.append(cherry_base)

    seen = set()
    for d in search_dirs:
        d = os.path.abspath(d)
        if d in seen:
            continue
        seen.add(d)
        candidate = os.path.join(d, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def _build_normalized_map(fill_data: list) -> dict:
    """构建规范化映射表：去空格/标点的字段名 → value"""
    normalized_map = {}
    for f in fill_data:
        norm = _normalize_field_name(f['field_name'])
        normalized_map[norm] = f['value']
        normalized_map[f['field_name']] = f['value']
    return normalized_map


def _match_field_value(
    cell_text: str,
    fill_map: dict,
    normalized_map: dict,
    field_synonyms: dict,
    cache: dict = None
) -> str | None:
    """模块级字段匹配：精确→规范化→同义词→分词→包含 五级匹配"""
    if cache is not None and cell_text in cache:
        return cache[cell_text]

    text = cell_text.strip()
    result = None

    # 1. 精确匹配
    if text in fill_map:
        result = fill_map[text]
    # 2. 规范化匹配
    elif text not in fill_map:
        norm = _normalize_field_name(text)
        if norm in normalized_map:
            result = normalized_map[norm]
        # 3. 同义词映射匹配
        elif norm in field_synonyms:
            standard_name = field_synonyms[norm]
            for key, val in fill_map.items():
                if _normalize_field_name(key) == standard_name:
                    result = val
                    break
        # 4. 分词匹配（处理"学历/学位"这类复合字段）
        if result is None:
            parts = re.split(r'[\s/\\|（）()【】\[\]、,\-_.~!@#$%^&*+=?<>"\'\`]+', text)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if part in fill_map:
                    result = fill_map[part]
                    break
                part_norm = _normalize_field_name(part)
                if part_norm in normalized_map:
                    result = normalized_map[part_norm]
                    break
                if part_norm in field_synonyms:
                    standard_name = field_synonyms[part_norm]
                    for key, val in fill_map.items():
                        if _normalize_field_name(key) == standard_name:
                            result = val
                            break
                    if result:
                        break
        # 5. 包含匹配（兜底）
        if result is None:
            for key, val in fill_map.items():
                norm_key = _normalize_field_name(key)
                if norm_key in norm or norm in norm_key:
                    result = val
                    break

    if cache is not None:
        cache[cell_text] = result
    return result


def _apply_font_to_run(run, font_name: str, font_size_pt: float, font_color: str):
    """为填充的 run 应用默认字体和颜色（模块级共享）"""
    from docx.shared import Pt
    run.font.name = font_name
    from docx.oxml.ns import qn
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        from docx.oxml import OxmlElement
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), font_name)
    run.font.size = Pt(font_size_pt)
    # 解析颜色
    COLOR_MAP = {
        '黑色': '000000', '黑': '000000',
        '红色': 'FF0000', '红': 'FF0000',
        '绿色': '00FF00', '绿': '00FF00',
        '蓝色': '0000FF', '蓝': '0000FF',
        '黄色': 'FFFF00', '黄': 'FFFF00',
        '紫色': '800080', '紫': '800080',
        '橙色': 'FFA500', '橙': 'FFA500',
        '白色': 'FFFFFF', '白': 'FFFFFF',
        '灰色': '808080', '灰': '808080',
        '粉色': 'FFC0CB', '粉': 'FFC0CB',
        '棕色': 'A52A2A', '棕': 'A52A2A',
    }
    try:
        from docx.shared import RGBColor
        color_input = font_color.strip().lower()
        if color_input in COLOR_MAP:
            color_hex = COLOR_MAP[color_input]
        else:
            color_hex = font_color.lstrip('#').upper()
        if len(color_hex) == 6:
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
            run.font.color.rgb = RGBColor(r, g, b)
        else:
            run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    except (ValueError, AttributeError):
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def _copy_run_rpr(source_run):
    """深拷贝源 run 的 rPr 元素（字体/字号/颜色/下划线等全部格式）。
    返回 None 表示源 run 无直接格式（继承文档/段落样式）。"""
    from docx.oxml.ns import qn
    import copy as _copy
    rPr = source_run._element.find(qn('w:rPr'))
    return _copy.deepcopy(rPr) if rPr is not None else None


def _apply_rpr(run, rpr_element):
    """将 rPr 元素应用到 run（替换其现有 rPr）。rpr_element 为 None 时不动。"""
    if rpr_element is None:
        return
    from docx.oxml.ns import qn
    existing = run._element.find(qn('w:rPr'))
    if existing is not None:
        run._element.remove(existing)
    run._element.insert(0, rpr_element)


def _copy_para_mark_rpr(para):
    """深拷贝段落标记的 rPr（w:pPr/w:rPr），即「在 Word 里往该段落打字会得到的格式」。
    返回 None 表示段落标记无直接格式（需继承样式链）。"""
    from docx.oxml.ns import qn
    import copy as _copy
    pPr = para._p.pPr
    if pPr is None:
        return None
    rPr = pPr.find(qn('w:rPr'))
    if rPr is None:
        return None
    rPr = _copy.deepcopy(rPr)
    # 段落标记的 rPr 是 CT_ParaRPr，允许携带修订相关子元素；而 run 的 rPr 是 CT_RPr，
    # 不允许这些元素。深拷贝后必须剔除，否则产物 XML 不合 OOXML schema。
    for tag in ('w:ins', 'w:del', 'w:moveFrom', 'w:moveTo', 'w:rPrChange'):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
    return rPr


def _fill_cell_preserving_format(cell, value, font_name: str, font_size_pt: float, font_color: str):
    """填充单元格并尽量保留原格式（格式保持核心）。

    优先级：
    1. 单元格内含下划线占位的 run → 就地替换其文本（该 run 的 rPr 完整保留，
       下划线等样式不丢失，值为黑色/模板色而非强制默认蓝）；
    2. 单元格内首个非空 run → 追加新 run 并复制其 rPr（与模板观感一致）；
    3. 均无 → 追加 run 并继承段落标记格式（w:pPr/w:rPr，即空格自己的要求，
       与相邻单元格无关）；段落标记也无格式时保持无 rPr，交由样式链
       （段落样式→表格样式→文档默认）渲染，始终避免强制宋体/字号/颜色破坏模板观感。
    """
    value_str = str(value)
    if value_str == '':
        return
    # 1) 就地替换含下划线占位的 run
    for p in cell.paragraphs:
        for r in p.runs:
            if '_' in r.text or '＿' in r.text:
                new_text = re.sub(r'[_＿]+', '', r.text)
                r.text = f"{new_text}{value_str}"
                return
    # 2) 复制单元格内首个非空 run 的格式
    ref_rpr = None
    for p in cell.paragraphs:
        for r in p.runs:
            if r.text.strip():
                ref_rpr = _copy_run_rpr(r)
                break
        if ref_rpr is not None:
            break
    run = cell.paragraphs[0].add_run(value_str)
    if ref_rpr is not None:
        _apply_rpr(run, ref_rpr)
    else:
        # 3) 无参考 run：继承段落标记格式（空格自己的要求，与相邻单元格无关）；
        #    段落标记也无格式时保持无 rPr，交由样式链渲染
        _apply_rpr(run, _copy_para_mark_rpr(cell.paragraphs[0]))


def _fill_para_preserving_format(para, new_text: str):
    """重建段落文本但保留原段落首个 run 的格式；无参考格式时继承文档默认。
    （避免整段 clear 后强制默认字体破坏模板观感）"""
    from docx.oxml.ns import qn
    import copy as _copy
    ref_rpr = None
    for r in para.runs:
        rPr = r._element.find(qn('w:rPr'))
        if rPr is not None:
            ref_rpr = _copy.deepcopy(rPr)
            break
    # 注意：python-docx 无法解析 w:jc val="start"/"end"（Word 原生值），读取会抛
    # ValueError。此类对齐值保存在 pPr 中，para.clear() 只清内容不清 pPr，
    # 因此读取失败时直接放弃保存/恢复，版式仍然保留。
    try:
        saved_alignment = para.alignment
    except ValueError:
        saved_alignment = None
    para.clear()
    run = para.add_run(new_text)
    if ref_rpr is not None:
        _apply_rpr(run, ref_rpr)
    if saved_alignment is not None:
        try:
            para.alignment = saved_alignment
        except ValueError:
            pass


def _build_table_grid(table) -> list:
    """构建表格的逻辑网格（坐标 + 文本 + 合并信息），供 LLM 理解结构与按坐标填充。

    返回:
        [ [ {col, row, text, grid_span, vmerge, is_empty}, ... ], ... ]
        其中 row/col 为逻辑坐标；grid_span>1 表示横向合并；
        vmerge 为 'restart'/'continue'/None，表示纵向合并状态。
    """
    grid = []
    for ri, row in enumerate(table.rows):
        row_cells = []
        for ci, cell in enumerate(row.cells):
            tc = cell._tc
            grid_span = 1
            vmerge = None
            tcPr = tc.tcPr
            if tcPr is not None:
                gs = tcPr.gridSpan
                if gs is not None:
                    try:
                        grid_span = int(gs.val)
                    except (ValueError, TypeError):
                        grid_span = 1
                vm = tcPr.vMerge
                if vm is not None:
                    # vMerge val 为空表示 continue，restart 表示起始
                    vmerge = vm.val if vm.val else 'continue'
            text = cell.text.strip()
            row_cells.append({
                "col": ci,
                "row": ri,
                "text": text,
                "grid_span": grid_span,
                "vmerge": vmerge,
                "is_empty": _is_empty_cell(text),
            })
        grid.append(row_cells)
    return grid


def _resolve_write_cell(table, r: int, c: int):
    """根据逻辑坐标 (r, c) 解析到实际可写的 cell（处理纵向合并）。

    纵向合并续行（vMerge continue）的空单元格在物理上是独立的空 tc，
    需向上回溯到合并起始行（restart）的 tc 写入，才能保持视觉上的合并效果。
    """
    try:
        cell = table.rows[r].cells[c]
    except IndexError:
        return None
    tcPr = cell._tc.tcPr
    if tcPr is not None and tcPr.vMerge is not None and tcPr.vMerge.val in (None, 'continue'):
        for ur in range(r - 1, -1, -1):
            try:
                up_cell = table.rows[ur].cells[c]
            except IndexError:
                break
            up_tcPr = up_cell._tc.tcPr
            if up_tcPr is None or up_tcPr.vMerge is None:
                return up_cell
            if up_tcPr.vMerge.val == 'restart':
                return up_cell
        return cell
    return cell


def _analyze_layout_complexity(doc) -> dict:
    """分析 docx 布局复杂度，返回置信度与特征标志。

    命中以下任一特征即视为低置信度（需走 LLM 坐标映射通道）：
    - 合并单元格（gridSpan / vMerge）
    - 嵌套表格
    - 标签+下划线同格（"姓名：____" 等，MCP 纯空单元格推断会漏填）
    """
    flags = []
    has_merge = False
    has_nested = False
    has_inline_placeholder = False
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                tcPr = cell._tc.tcPr
                if tcPr is not None:
                    gs = tcPr.gridSpan
                    vm = tcPr.vMerge
                    if (gs is not None and gs.val) or vm is not None:
                        has_merge = True
                if cell.tables:
                    has_nested = True
                text = cell.text.strip()
                if text and ('____' in cell.text or '＿' in cell.text) and not _is_empty_cell(text):
                    has_inline_placeholder = True
    for para in doc.paragraphs:
        if '____' in para.text or '＿' in para.text:
            has_inline_placeholder = True
    if has_merge:
        flags.append('merged_cells')
    if has_nested:
        flags.append('nested_tables')
    if has_inline_placeholder:
        flags.append('inline_placeholder')
    if flags:
        return {"confidence": "low", "flags": flags}
    return {"confidence": "high", "flags": []}


def _make_error_json(code: str, message: str, detail: str = None) -> str:
    """统一错误响应格式"""
    result = {"status": "error", "code": code, "message": message}
    if detail:
        result["detail"] = detail
    return json.dumps(result, ensure_ascii=False)


def _cleanup_temp_file(path):
    """删除 Base64 入口创建的临时文件（失败静默，不影响返回结果）。"""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _unique_output_path(dir_path: str, stem: str, ext: str) -> str:
    """生成带秒级时间戳的输出路径；同名文件已存在时追加短 uuid，避免同分钟覆盖。"""
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y%m%d%H%M%S")
    os.makedirs(dir_path, exist_ok=True)
    candidate = os.path.join(dir_path, f"{stem}_{ts}{ext}")
    if os.path.exists(candidate):
        candidate = os.path.join(dir_path, f"{stem}_{ts}_{uuid.uuid4().hex[:6]}{ext}")
    return candidate


# 段落字段：「标签：占位」；支持同一段落多个占位（如 "姓名：____　电话：________"）
# 标签段排除冒号、下划线及中文标点，避免把整句当字段名
# MULTILINE：单元格多行文本按行识别（$ 匹配行尾），否则多行单元格只能识别最后一行
_PARA_FIELD_RE = re.compile(
    r'([^\n：:_＿，,；;。]{1,30})[：:][ \t\u3000]*([_＿]{1,}|$)', re.MULTILINE)
# 无冒号、以 3+ 空白结尾的纯字段名行（多行单元格按行匹配，不能先 strip 整段）
_PARA_FIELD_SPACE_RE = re.compile(
    r'^([^\n：:_＿，,；;。]{1,30})[ \t\u3000]{3,}$', re.MULTILINE)


def _extract_para_field_names(text: str) -> list:
    """提取文本中的全部字段名（支持同段/多行多占位）。"""
    text = text or ''
    names = []
    for m in _PARA_FIELD_RE.finditer(text):
        label = m.group(1).strip()
        if label:
            names.append(label)
    if not names:
        m = _PARA_FIELD_SPACE_RE.search(text)
        if m and m.group(1).strip():
            names.append(m.group(1).strip())
    return names


def _iter_story_paragraphs(doc):
    """遍历正文 + 页眉页脚 + 文本框中的段落（按 XML 元素去重）。

    python-docx 的 doc.paragraphs 只覆盖正文顶层段落，页眉/页脚/文本框
    中的占位符需要单独遍历才能被解析与填充。
    """
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    seen = set()

    def _emit(paras):
        for para in paras:
            key = para._p
            if key in seen:
                continue
            seen.add(key)
            yield para

    yield from _emit(doc.paragraphs)

    parts = []
    for section in doc.sections:
        for attr in ('header', 'footer', 'first_page_header', 'first_page_footer',
                     'even_page_header', 'even_page_footer'):
            try:
                part = getattr(section, attr)
                if part.is_linked_to_previous:
                    continue
                parts.append(part)
            except Exception:
                continue
        # 页眉页脚段落（延迟到 parts 收集后统一处理）
    for part in parts:
        try:
            yield from _emit(part.paragraphs)
        except Exception:
            pass

    # 文本框：正文与页眉页脚中的 w:txbxContent
    roots = [doc.element.body]
    for part in parts:
        try:
            roots.append(part._element)
        except Exception:
            pass
    for root in roots:
        for box in root.iter(qn('w:txbxContent')):
            for p_el in box.iter(qn('w:p')):
                if p_el in seen:
                    continue
                seen.add(p_el)
                yield Paragraph(p_el, None)


# =====================================================================
# 表单解析/填充共享工具（fill_word_form 与 _do_fill_docx 复用，避免逻辑漂移）
# =====================================================================
# 内联占位：2+ 半角/全角下划线（"姓名：____ 电话：＿＿＿＿"）
_INLINE_PLACEHOLDER_RE = re.compile(r'[_＿]{2,}')
# 用于「标签含空格」场景：把空白压缩掉后再匹配（"姓    名" → "姓名"）
_COMPACT_WS_RE = re.compile(r'\s+')


def _compact_ws(text: str) -> str:
    """去掉全部空白（含全角空格），仅用于字段名/标签的宽松比对。"""
    return _COMPACT_WS_RE.sub('', text or '')


def _iter_table_cells(table, _nested: bool = False):
    """遍历表格单元格（递归进入嵌套表）。

    yield: (table, row_index, cell_index, cell, has_nested, is_nested)
    - table 为单元格所属的表格（嵌套表的行/列回溯必须用它，不能用顶层表）；
    - has_nested=True 表示该单元格是嵌套表容器，其文本不含子表内容，
      填充扫描时应跳过、交由递归的子表处理；
    - 合并单元格会按逻辑坐标重复产出，与非合并时的行为保持一致。
    """
    for ri, row in enumerate(table.rows):
        for ci, cell in enumerate(row.cells):
            has_nested = bool(cell.tables)
            yield table, ri, ci, cell, has_nested, _nested
            if has_nested:
                for child in cell.tables:
                    yield from _iter_table_cells(child, True)


def _synonym_names(field_name: str, field_synonyms: dict = None) -> set:
    """返回与 field_name 同义的全部名字（按标准名归并，如 联系电话/手机号）。

    仅比较「同义词值 == 字段名」会漏掉「两者都映射到同一个标准名」的情况：
    fill_data 用 联系电话，表单写 手机号，二者都归一到 手机号码。
    """
    names = {field_name}
    synonyms = field_synonyms or {}
    norm_fn = _normalize_field_name(field_name)
    canonical = synonyms.get(norm_fn, norm_fn)
    for syn_key, standard in synonyms.items():
        if standard == canonical or _normalize_field_name(syn_key) == norm_fn:
            names.add(syn_key)
    names.discard('')
    return names


def _collect_name_variants(fill_data: list, field_synonyms: dict = None) -> set:
    """收集字段名的所有匹配变体：原始名、去标点名、去空白名、同义词。"""
    variants = set()
    for f in fill_data:
        fn = (f or {}).get('field_name', '')
        if not fn:
            continue
        for name in _synonym_names(fn, field_synonyms):
            variants.add(name)
            variants.add(_normalize_field_name(name))
            variants.add(_compact_ws(name))
    variants.discard('')
    return variants


def _build_field_filter(fill_data: list, field_synonyms: dict = None):
    """构建段落级快速过滤正则；无字段时返回 None。"""
    parts = sorted(_collect_name_variants(fill_data, field_synonyms), key=len, reverse=True)
    if not parts:
        return None
    return re.compile('|'.join(re.escape(p) for p in parts))


def _para_matches_filter(text: str, filter_re) -> bool:
    """过滤判断：原文命中，或去掉空白后命中（修复「姓 名」「姓　名」被整段跳过）。"""
    if filter_re is None:
        return True
    if filter_re.search(text or ''):
        return True
    compact = _compact_ws(text)
    return bool(compact) and bool(filter_re.search(compact))


def _has_inline_placeholder(text: str) -> bool:
    """是否含内联占位下划线（半角 _ / 全角 ＿）。"""
    return bool(_INLINE_PLACEHOLDER_RE.search(text or ''))


def _has_placeholder(text: str) -> bool:
    """段落是否有可填占位：内联下划线、行尾冒号（"姓 名："）或行尾大段空白（"学历　　　"）。"""
    text = text or ''
    if _has_inline_placeholder(text):
        return True
    if text.rstrip().endswith(('：', ':')):
        return True
    # 纯空白占位（半角/全角空格），Word 表单常用制表位对齐
    return bool(re.search(r'[ \t\u3000]{2,}$', text))


def _build_para_patterns(fill_data: list, field_synonyms: dict = None, inline: bool = False) -> list:
    """预编译段落替换模式，返回 [(field_name, value, compiled), ...]。

    inline=True 用于「非空单元格内的标签+下划线」场景，只匹配带下划线的占位；
    inline=False 用于整段填写，额外支持「标签+大段空白」与「行尾冒号」。
    模式按长度倒序，长字段名优先（避免「姓名」抢先匹配「姓名拼音」）。
    """
    patterns = []
    for f in fill_data:
        fn = (f or {}).get('field_name', '')
        val = (f or {}).get('value', '')
        if not fn:
            continue
        for name in _synonym_names(fn, field_synonyms):
            # 模式1：字面量字段名；模式2：允许字段名中间夹空格（"姓    名"）
            name_patterns = [re.escape(name), r'[\s：:]*'.join(re.escape(c) for c in name)]
            if inline:
                tails = [r'[：:][ \t\u3000]*[_＿]+', r'[ \t]*[_＿]+']
            else:
                tails = [
                    r'[：:][ \t\u3000]*[_＿ \t\u3000]*',   # "姓名：____" / "姓名："
                    r'[ \t\u3000]{2,}[_＿ \t\u3000]*',  # "姓名    ____" / "学历　　　"（全角空格）
                    r'[：:][ \t]*$',            # 行尾冒号（多行单元格的字段行）
                ]
            for tail in tails:
                for name_pat in name_patterns:
                    # 标签与占位之间只允许空白/ASCII 修饰（如 "姓名（曾用名）：" 的
                    # 名称本身已完整包含在 name_pat 中）；禁止跨越中文字符，
                    # 否则短字段「姓名」会把「姓名拼音：____」误判为自己的占位。
                    patterns.append((
                        fn, val,
                        re.compile(r'(' + name_pat + r'[^\u4e00-\u9fa5：:]*?)' + tail, re.MULTILINE)
                    ))
    patterns.sort(key=lambda item: len(item[2].pattern), reverse=True)
    return patterns


def _apply_para_replacements(text: str, patterns: list) -> tuple:
    """在段落文本上执行替换，返回 (new_text, [(field_name, count), ...])。

    必须使用函数式替换：替换串里的反斜杠、\\1、\\t 等会被 re.sub 当作转义/反向
    引用解析，导致用户填写的值被篡改（如 "C:\\temp" 变成 "C:<tab>emp"）。
    """
    new_text = text or ''
    counts = {}
    for fn, val, pat in patterns:
        # 同一字段在本段落只应用一次模式：字面量模式与「标签夹空格」模式会先后命中
        # 同一占位（第一次替换后 "姓名：张三" 仍满足 "姓名：" 尾巴），导致值重复写入
        if counts.get(fn):
            continue
        value_str = str(val)
        new_text, n = pat.subn(lambda m: m.group(1) + '：' + value_str, new_text)
        if n:
            counts[fn] = counts.get(fn, 0) + n
    return new_text, list(counts.items())


def _fill_placeholder_paragraphs(paragraphs, patterns: list) -> tuple:
    """在给定段落集合中就地替换内联占位，返回 (count, [(field_name, count), ...])。"""
    total = 0
    matched = {}
    for para in paragraphs:
        text = para.text
        if not text or not _has_inline_placeholder(text):
            continue
        new_text, hits = _apply_para_replacements(text, patterns)
        if not hits or new_text == text:
            continue
        _fill_para_preserving_format(para, new_text)
        for fn, n in hits:
            matched[fn] = matched.get(fn, 0) + n
            total += n
    return total, list(matched.items())


def _flatten_person_info(data: dict) -> dict:
    """将分类个人信息（个人基本信息/教育背景/...）扁平化为 key→value"""
    flat = {}
    for category, fields in data.items():
        if isinstance(fields, dict):
            for key, value in fields.items():
                if value and value != "【待补充】":
                    flat[key] = value
        elif isinstance(fields, list):
            # 直接是数组格式 [{field_name: x, value: y}, ...]
            for item in fields:
                if isinstance(item, dict) and 'field_name' in item:
                    flat[item['field_name']] = item.get('value', '')
        else:
            # 扁平键值对（值非 dict/list），如 {"姓名": "张三"}
            if fields and fields != "【待补充】":
                flat[category] = fields
    return flat


def _parse_docx_fields(doc) -> list:
    """从 Word 文档中提取所有待填写字段名（共享逻辑）"""
    fields = []

    # 从段落提取（正文 + 页眉页脚 + 文本框，支持同段多占位）
    for para in _iter_story_paragraphs(doc):
        raw_text = para.text
        if not raw_text.strip():
            continue
        for name in _extract_para_field_names(raw_text):
            fields.append(name)

    # 从表格提取（递归嵌套表 + 内联占位单元格）
    for table in doc.tables:
        for tbl, ri, ci, cell, has_nested, _nested in _iter_table_cells(table):
            if has_nested:
                continue  # 嵌套表容器格，字段由子表递归产出
            text = cell.text.strip()
            if not _is_empty_cell(text):
                # 非空但含内联占位（"姓名：____"）：「标签+下划线同格」也需要解析出字段
                if _has_inline_placeholder(text):
                    for name in _extract_para_field_names(cell.text):
                        fields.append(name)
                continue

            field_name = None
            if ci > 0:
                for left_ci in range(ci - 1, -1, -1):
                    left = tbl.rows[ri].cells[left_ci].text.strip()
                    if left and not _is_empty_cell(left):
                        field_name = left
                        break
            if not field_name and ri > 0:
                for up_ri in range(ri - 1, -1, -1):
                    above = tbl.rows[up_ri].cells[ci].text.strip()
                    if above and not _is_empty_cell(above):
                        field_name = above
                        break
            if field_name:
                fields.append(field_name)

    return fields


def _do_fill_docx(
    doc, fill_data: list, field_synonyms: dict,
    font_name: str, font_size_pt: float, font_color: str
) -> tuple:
    """执行实际的 docx 填充操作，返回 (filled_count, unmatched_names, pending_names)

    与 _do_fill_docx_cells 配合：先填充表格单元格，再填充段落。
    filled_count 由两部分累计。
    """
    fill_map = {f['field_name']: f['value'] for f in fill_data}
    normalized_map = _build_normalized_map(fill_data)
    match_cache = {}
    used_field_names = set()
    filled_count = 0

    # ============ 填充表格单元格 ============
    inline_patterns = _build_para_patterns(fill_data, field_synonyms, inline=True)
    for table in doc.tables:
        for tbl, ri, ci, cell, has_nested, _nested in _iter_table_cells(table):
            if has_nested:
                continue  # 嵌套表容器格由递归子表处理
            cell_text = cell.text.strip()
            if not _is_empty_cell(cell_text):
                # 非空单元格：仅处理内联占位（如「姓名：____ 电话：＿＿＿＿」）
                if _has_inline_placeholder(cell_text):
                    n, hits = _fill_placeholder_paragraphs(cell.paragraphs, inline_patterns)
                    if n:
                        filled_count += n
                        for fn, _cnt in hits:
                            used_field_names.add(fn)
                continue

            fill_value = None
            matched_field = None

            if ci > 0:
                for left_ci in range(ci - 1, -1, -1):
                    left_text = tbl.rows[ri].cells[left_ci].text.strip()
                    if left_text and not _is_empty_cell(left_text):
                        fill_value = _match_field_value(
                            left_text, fill_map, normalized_map,
                            field_synonyms, match_cache
                        )
                        if fill_value:
                            matched_field = left_text
                            break

            if not fill_value and ri > 0:
                for up_ri in range(ri - 1, -1, -1):
                    above_text = tbl.rows[up_ri].cells[ci].text.strip()
                    if above_text and not _is_empty_cell(above_text):
                        fill_value = _match_field_value(
                            above_text, fill_map, normalized_map,
                            field_synonyms, match_cache
                        )
                        if fill_value:
                            matched_field = above_text
                            break

            if fill_value:
                # 格式保持：就地替换占位 run / 复制单元格内参考 run 格式 / 继承文档默认
                _fill_cell_preserving_format(cell, fill_value, font_name, font_size_pt, font_color)
                filled_count += 1
                if matched_field:
                    if matched_field in fill_map:
                        used_field_names.add(matched_field)
                    else:
                        norm_matched = _normalize_field_name(matched_field)
                        for fn in fill_map:
                            if _normalize_field_name(fn) == norm_matched:
                                used_field_names.add(fn)
                                break
                        else:
                            if norm_matched in field_synonyms:
                                standard = field_synonyms[norm_matched]
                                for fn in fill_map:
                                    if _normalize_field_name(fn) == standard:
                                        used_field_names.add(fn)
                                        break

    # ============ 填充段落 ============
    field_filter_re = _build_field_filter(fill_data, field_synonyms)
    para_patterns = _build_para_patterns(fill_data, field_synonyms)

    for para in _iter_story_paragraphs(doc):
        full_text = para.text
        if not full_text.strip():
            continue
        # 标签可能被空格拆开（"姓 名"），过滤时同时比对去空白文本
        if not _para_matches_filter(full_text, field_filter_re):
            continue
        if not _has_placeholder(full_text):
            continue

        # 不 break：同一段落中的多个占位符一次性全部替换
        new_text, matched_fields = _apply_para_replacements(full_text, para_patterns)
        if matched_fields and new_text != full_text:
            # 格式保持：重建段落但保留原段落首个 run 的格式（无则继承文档默认）
            _fill_para_preserving_format(para, new_text)
            for fn, n in matched_fields:
                filled_count += n
                used_field_names.add(fn)

    unmatched = [fn for fn, val in fill_map.items() if fn not in used_field_names]
    pending = [fn for fn, val in fill_map.items() if val == "【待补充】"]
    return filled_count, unmatched, pending


def register_auto_fill_tools(
    mcp: FastMCP,
    base_dir: str = "/data",
    synonyms_config: str = None,
    server_base_url: str = "",
    **kwargs
) -> None:
    """
    向 FastMCP 实例注册自动填表相关工具

    Args:
        mcp: FastMCP 服务器实例
        base_dir: 写入沙箱根目录
        synonyms_config: 同义词配置文件路径（可选）。支持 JSON 文件，优先级：
            参数指定 > 环境变量 FIELD_SYNONYMS_CONFIG > base_dir/config/field_synonyms.json > 内置默认
        server_base_url: 服务器对外基础 URL，用于生成文件下载链接，如 http://192.168.1.10:19120
    """

    # 加载字段同义词映射（支持外部配置文件，Docker 友好）
    FIELD_SYNONYMS = _load_field_synonyms(synonyms_config, base_dir)

    def _make_download_url(abs_file_path: str) -> str:
        """如果文件在 base_dir 下，生成可下载 URL"""
        url_base = server_base_url
        # 未配置时，自动从当前 HTTP 请求头探测（支持反向代理 X-Forwarded-*）
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

    def _resolve_read_path(path: str) -> str:
        """解析读取路径，支持完整路径、Windows路径(Docker)和文件名自动搜索"""
        # Docker容器内：将 Windows 绝对路径映射到挂载点
        from .file_tools import _map_windows_to_linux
        mapped = _map_windows_to_linux(path, base_dir)
        if mapped and os.path.exists(mapped):
            return mapped

        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            return abs_path

        # 如果是相对路径/纯文件名，在常见目录中搜索
        if not os.path.isabs(path):
            found = _search_file(path)
            if found:
                return found

        # Docker 内再尝试一次映射（可能路径未挂载）
        if mapped:
            raise ValueError(f"文件不存在: {path} (已尝试映射到 {mapped}，但文件不存在。请确认Docker挂载了宿主机目录)")

        raise ValueError(f"文件不存在: {path}")

    def _resolve_write_path(path: str) -> str:
        """解析写入路径，允许写入用户常见目录"""
        if not os.path.isabs(path):
            # 相对路径/纯文件名 → 落到沙箱 uploads 目录（与 smart_fill_form_local 行为一致）
            abs_path = os.path.abspath(os.path.join(base_dir, "uploads", path))
        else:
            abs_path = os.path.abspath(path)
        home = os.path.expanduser("~")
        allowed_dirs = [
            os.path.abspath(base_dir),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
        ]
        for allowed in allowed_dirs:
            if abs_path.startswith(os.path.abspath(allowed)):
                return abs_path
        raise ValueError(
            f"写入路径越权: {path}，仅允许: {base_dir}、Downloads、Desktop、Documents"
        )

    # =====================================================================
    # 工具1: read_knowledge_base
    # =====================================================================
    @mcp.tool()
    async def read_knowledge_base(kb_path: str = "personal_info.json", kb_data: str = "") -> str:
        """
        读取知识库中的个人信息

        支持两种模式:
        1. 文件模式：提供 kb_path，读取本地 JSON 文件
        2. 内联模式：提供 kb_data，直接解析 JSON 字符串（平台从知识库检索到的结果）

        Args:
            kb_path: 知识库文件路径（相对 base_dir），默认 personal_info.json
            kb_data: 知识库 JSON 数据字符串（优先使用，跳过文件读取）

        Returns:
            JSON 字符串，包含所有个人信息
        """
        # 优先使用 kb_data（平台知识库直接传入的数据）
        if kb_data and kb_data.strip():
            try:
                # 验证JSON格式
                data = json.loads(kb_data)
                return json.dumps(data, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                # 不是JSON，尝试作为文本用 read_personal_info_from_text 解析
                return await read_personal_info_from_text(kb_data)

        loop = asyncio.get_event_loop()
        def _read():
            full_path = _resolve_read_path(os.path.join(base_dir, kb_path))
            with open(full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return json.dumps(data, ensure_ascii=False, indent=2)
        return await loop.run_in_executor(None, _read)

    # =====================================================================
    # 工具2: read_personal_info_from_text
    # =====================================================================
    @mcp.tool()
    async def read_personal_info_from_text(text: str) -> str:
        """
        从用户输入的纯文本中解析并结构化个人信息

        支持格式:
            - 自然语言描述: 我叫张三，男，1990年出生，电话13800138000
            - 键值对格式: 姓名：张三 / 性别：男 / 电话：13800138000
            - JSON 字符串

        Args:
            text: 用户输入的个人信息文本

        Returns:
            标准化的 JSON 格式个人信息
        """
        # 先尝试直接解析 JSON
        try:
            data = json.loads(text)
            if any(key in data for key in ["个人基本信息", "教育背景", "工作信息"]):
                return json.dumps(data, ensure_ascii=False, indent=2)
            return json.dumps({"个人基本信息": data}, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass

        info = {
            "个人基本信息": {},
            "教育背景": {},
            "工作信息": {},
            "家庭信息": {},
            "银行账户": {}
        }

        # 常见字段映射
        field_mapping = {
            "姓名": ("个人基本信息", "姓名"),
            "name": ("个人基本信息", "姓名"),
            "性别": ("个人基本信息", "性别"),
            "sex": ("个人基本信息", "性别"),
            "出生日期": ("个人基本信息", "出生日期"),
            "出生年月": ("个人基本信息", "出生日期"),
            "身份证号": ("个人基本信息", "身份证号"),
            "证件号码": ("个人基本信息", "身份证号"),
            "身份证": ("个人基本信息", "身份证号"),
            "手机": ("个人基本信息", "手机号码"),
            "电话": ("个人基本信息", "手机号码"),
            "手机号码": ("个人基本信息", "手机号码"),
            "联系电话": ("个人基本信息", "手机号码"),
            "邮箱": ("个人基本信息", "电子邮箱"),
            "电子邮箱": ("个人基本信息", "电子邮箱"),
            "email": ("个人基本信息", "电子邮箱"),
            "民族": ("个人基本信息", "民族"),
            "政治面貌": ("个人基本信息", "政治面貌"),
            "学历": ("教育背景", "最高学历"),
            "最高学历": ("教育背景", "最高学历"),
            "毕业院校": ("教育背景", "毕业院校"),
            "学校": ("教育背景", "毕业院校"),
            "专业": ("教育背景", "专业"),
            "毕业时间": ("教育背景", "毕业时间"),
            "工作单位": ("工作信息", "现工作单位"),
            "单位": ("工作信息", "现工作单位"),
            "公司": ("工作信息", "现工作单位"),
            "职务": ("工作信息", "职务"),
            "岗位": ("工作信息", "职务"),
            "职称": ("工作信息", "职务"),
            "部门": ("工作信息", "部门"),
            "工作年限": ("工作信息", "工作年限"),
            "住址": ("家庭信息", "家庭住址"),
            "家庭住址": ("家庭信息", "家庭住址"),
            "地址": ("家庭信息", "家庭住址"),
            "紧急联系人": ("家庭信息", "紧急联系人"),
            "紧急联系人电话": ("家庭信息", "紧急联系人电话"),
            "婚姻状况": ("家庭信息", "婚姻状况"),
            "开户行": ("银行账户", "开户行"),
            "银行": ("银行账户", "开户行"),
            "银行卡号": ("银行账户", "银行卡号"),
            "卡号": ("银行账户", "银行卡号"),
            "账号": ("银行账户", "银行卡号"),
            "开户行地址": ("银行账户", "开户行地址"),
        }

        # 自然语言正则模式
        nlp_patterns = [
            (r'我叫([\u4e00-\u9fa5]{2,4})', ("个人基本信息", "姓名")),
            (r'姓名是([\u4e00-\u9fa5]{2,4})', ("个人基本信息", "姓名")),
            (r'性别[是为]?(男|女)', ("个人基本信息", "性别")),
            (r'(\d{4})年?出生', ("个人基本信息", "出生日期")),
            (r'出生[于在]?(\d{4})', ("个人基本信息", "出生日期")),
            (r'(?:手机|电话|联系)[号码]?是?(\d{11})', ("个人基本信息", "手机号码")),
            (r'(\d{11})', ("个人基本信息", "手机号码")),
            (r'身份证[号码]?是?(\d{17}[\dXx])', ("个人基本信息", "身份证号")),
            (r'(\d{17}[\dXx])', ("个人基本信息", "身份证号")),
            (r'邮箱[是为]?([\w.+-]+@[\w-]+\.[\w.]+)', ("个人基本信息", "电子邮箱")),
            (r'([\w.+-]+@[\w-]+\.[\w.]+)', ("个人基本信息", "电子邮箱")),
            (r'民族[是为]?([\u4e00-\u9fa5]+族)', ("个人基本信息", "民族")),
            (r'政治面貌[是为]?(党员|团员|群众|民主党派)', ("个人基本信息", "政治面貌")),
            (r'学历[是为]?(博士|硕士|本科|大专|中专|高中|初中)', ("教育背景", "最高学历")),
            (r'毕业[于在]?([\u4e00-\u9fa5]+大学[\u4e00-\u9fa5]*)', ("教育背景", "毕业院校")),
            (r'工作[于在]?([\u4e00-\u9fa5]+公司[\u4e00-\u9fa5]*)', ("工作信息", "现工作单位")),
            (r'开户行[是为]?([\u4e00-\u9fa5]+银行[\u4e00-\u9fa5]*)', ("银行账户", "开户行")),
            (r'银行卡号[是为]?(\d{16,19})', ("银行账户", "银行卡号")),
        ]

        # 先尝试自然语言模式匹配
        for pattern, (category, field) in nlp_patterns:
            match = re.search(pattern, text)
            if match:
                info[category][field] = match.group(1)

        # 再按行解析键值对格式
        for line in text.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue

                # 优先用中文冒号和英文冒号，空格分隔放在最后（避免误解析）
                parsed = False
                for sep in ["：", ":", "="]:
                    if sep in line:
                        parts = line.split(sep, 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            if key and value:
                                if key in field_mapping:
                                    category, field = field_mapping[key]
                                    info[category][field] = value
                                else:
                                    info["个人基本信息"][key] = value
                                parsed = True
                            break
                if parsed:
                    continue
                # 空格分隔作为最后手段（要求 key 在映射表中才解析，避免误解析普通句子）
                if " " in line:
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        if key in field_mapping and value:
                            category, field = field_mapping[key]
                            info[category][field] = value

        # 清理空分类
        info = {k: v for k, v in info.items() if v}

        return json.dumps(info, ensure_ascii=False, indent=2)

    # =====================================================================
    # 工具3: read_personal_info_from_file
    # =====================================================================
    @mcp.tool()
    async def read_personal_info_from_file(file_path: str) -> str:
        """
        从用户上传的个人信息文件读取数据

        支持格式:
            - JSON 文件 (.json)
            - Word 文档 (.docx) - 从表格或段落提取
            - Excel 文件 (.xlsx/.xls) - 从表格提取
            - 文本文件 (.txt) - 按行解析键值对

        Args:
            file_path: 个人信息文件的完整路径，请务必传入绝对路径

        Returns:
            标准化的 JSON 格式个人信息
        """
        safe_path = _resolve_read_path(file_path)
        ext = os.path.splitext(safe_path)[1].lower()

        if ext == '.json':
            loop = asyncio.get_event_loop()
            def _read_json():
                with open(safe_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return json.dumps(data, ensure_ascii=False, indent=2)
            return await loop.run_in_executor(None, _read_json)

        elif ext in ['.txt', '.text']:
            loop = asyncio.get_event_loop()
            def _read_txt():
                with open(safe_path, 'r', encoding='utf-8') as f:
                    return f.read()
            text = await loop.run_in_executor(None, _read_txt)
            return await read_personal_info_from_text(text)

        elif ext == '.docx':
            try:
                from docx import Document
            except ImportError:
                return "Error: 请安装 python-docx (pip install python-docx)"

            doc = Document(safe_path)
            info = {
                "个人基本信息": {},
                "教育背景": {},
                "工作信息": {},
                "家庭信息": {},
                "银行账户": {}
            }

            # 从段落提取键值对
            for para in doc.paragraphs:
                text = para.text.strip()
                if '：' in text or ':' in text:
                    parts = text.replace(':', '：').split('：', 1)
                    if len(parts) == 2:
                        key, value = parts[0].strip(), parts[1].strip()
                        if value and not _is_empty_cell(value):
                            info["个人基本信息"][key] = value

            # 从表格提取键值对（遍历所有列对，不只是前两列）
            for table in doc.tables:
                for row in table.rows:
                    cells = row.cells
                    # 遍历所有相邻列对 (0,1), (1,2), (2,3)...
                    for ci in range(len(cells) - 1):
                        key = cells[ci].text.strip()
                        value = cells[ci + 1].text.strip()
                        if key and value and not _is_empty_cell(value):
                            info["个人基本信息"][key] = value

            info = {k: v for k, v in info.items() if v}
            return json.dumps(info, ensure_ascii=False, indent=2)

        elif ext in ['.xlsx', '.xls']:
            if ext == '.xls':
                # openpyxl 只支持 OOXML 格式，解析 .xls 会抛 InvalidFileException
                return _make_error_json(
                    "UNSUPPORTED_FORMAT",
                    "旧版 .xls 格式不受支持，请另存为 .xlsx 后再读取"
                )
            try:
                import openpyxl
            except ImportError:
                return "Error: 请安装 openpyxl (pip install openpyxl)"

            wb = openpyxl.load_workbook(safe_path)
            ws = wb.active
            info = {"个人基本信息": {}}

            for row in ws.iter_rows(min_row=1, values_only=False):
                if len(row) >= 2:
                    key = str(row[0].value or '').strip()
                    value = str(row[1].value or '').strip()
                    if key and value:
                        info["个人基本信息"][key] = value

            info = {k: v for k, v in info.items() if v}
            return json.dumps(info, ensure_ascii=False, indent=2)

        else:
            return _make_error_json(
                "UNSUPPORTED_FORMAT",
                f"不支持的文件格式: {ext}，请使用 .json/.txt/.docx/.xlsx"
            )

    # =====================================================================
    # 工具4: merge_info_sources
    # =====================================================================
    @mcp.tool()
    async def merge_info_sources(sources_json: str) -> str:
        """
        合并多个信息源，按优先级解决冲突

        优先级（从高到低）:
            1. 用户直接输入的文本 (priority=1)
            2. 上传的个人信息文件 (priority=2)
            3. 本地知识库 (priority=3)

        priority 数值越小优先级越高，冲突时高优先级（小数值）胜出。

        Args:
            sources_json: JSON 字符串，格式:
                [{"source": "knowledge_base", "data": "{}", "priority": 3},
                 {"source": "user_text", "data": "{}", "priority": 1}]

        Returns:
            合并后的标准化 JSON 个人信息
        """
        sources = json.loads(sources_json)

        # 按优先级从低到高排序，这样高优先级的数据后写入会覆盖低优先级
        sources.sort(key=lambda x: x.get("priority", 99), reverse=True)

        merged = {
            "个人基本信息": {},
            "教育背景": {},
            "工作信息": {},
            "家庭信息": {},
            "银行账户": {}
        }

        merge_log = []

        for src in sources:
            source_name = src.get("source", "unknown")
            try:
                data = json.loads(src.get("data", "{}"))
            except json.JSONDecodeError:
                continue

            for category, fields in data.items():
                if category not in merged:
                    merged[category] = {}
                for key, value in fields.items():
                    if key in merged[category]:
                        old_val = merged[category][key]
                        merge_log.append(
                            f"[{source_name}] {category}.{key} = {value} (覆盖原值: {old_val})"
                        )
                    else:
                        merge_log.append(f"[{source_name}] {category}.{key} = {value}")
                    merged[category][key] = value

        # 清理空分类
        merged = {k: v for k, v in merged.items() if v}

        result = {
            "merged_data": merged,
            "merge_log": merge_log,
            "source_count": len(sources)
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    # =====================================================================
    # 工具4b: extract_personal_info_from_context — 从知识库上下文提取信息
    # =====================================================================
    @mcp.tool()
    async def extract_personal_info_from_context(context_text: str) -> str:
        """从知识库检索结果（可能包含多篇文档片段）中提取标准化个人信息。

解决平台知识库返回的是原始文档片段而非结构化 JSON 的问题。
内部综合多篇文档，自动去重、合并冲突字段。

Args:
    context_text: 知识库检索返回的原始文本/上下文（可包含多段、多文档）

Returns:
    JSON，包含标准化个人信息，可直接用于 fill_word_form_base64 的 fill_data_json

用法:
    1. 平台从知识库检索到结果
    2. 将检索结果原文传入此工具
    3. 得到标准化 JSON → 传给 fill_word_form_base64 的 fill_data_json
"""
        try:
            # 先用 read_personal_info_from_text 解析
            parsed = await read_personal_info_from_text(context_text)
            parsed_data = json.loads(parsed)

            # 扁平化分类结构为 [{field_name, value}, ...]
            flat = _flatten_person_info(parsed_data)
            fill_data = [{"field_name": k, "value": v} for k, v in flat.items()]

            result = {
                "status": "ok",
                "field_count": len(fill_data),
                "fill_data": fill_data,
                "usage": "将 fill_data 直接作为 fill_data_json 传入 fill_word_form_base64",
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return _make_error_json("EXTRACT_ERROR", str(e))

    # =====================================================================
    # 工具7: fill_word_form_base64 — 远程一站式填表（上传→解析→填充→下载）
    # =====================================================================
    @mcp.tool()
    async def fill_word_form_base64(
        file_base64: str,
        filename: str = "document.docx",
        fill_data_json: str = "[]",
        fill_cells_json: str = "",
        font_name: str = "宋体",
        font_size_pt: float = 12.0,
        font_color: str = "000000",
        return_base64: bool = False,
    ) -> str:
        """远程一站式填表：接收Base64编码的.docx文件，解析、填写、返回结果。

专门解决远程服务器无法访问客户端本地文件的场景。

Args:
    file_base64: Word文档的Base64编码字符串
    filename: 文档文件名（如 "个人简历空表.docx"），默认 document.docx
    fill_data_json: 填充数据JSON，格式 [{"field_name":"姓名","value":"张三"}, ...]
    fill_cells_json: 按坐标精确填充JSON（异形表推荐），格式
                     [{"table_index":0,"row":2,"col":3,"value":"张三"}, ...]
                     坐标来自 parse_word_form_base64 返回的 tables 网格
    font_name: 填充字体，默认 "宋体"
    font_size_pt: 字号（磅），默认 12.0
    font_color: 字体颜色，默认 "000000"（黑色）
    return_base64: 是否返回 filled_base64（默认 False，节省 Token）。
                   为 True 时会在结果中包含完整的 Base64 编码文档。

Returns:
    JSON，包含 output_filename、filled_count、total_fields、download_url 等。
    默认不返回 filled_base64，请使用 download_url 下载。
"""
        upload_path = None
        try:
            # 检查文件大小
            size_err = _check_base64_size(file_base64)
            if size_err:
                return _make_error_json("FILE_TOO_LARGE", size_err)

            # Step 1: 解码文件并保存到服务器（临时文件名，避免覆盖已有文件）
            raw = base64.b64decode(file_base64)
            safe_name = os.path.basename(filename)
            if not safe_name.lower().endswith('.docx'):
                safe_name += '.docx'
            tmp_name = f"tmp_{uuid.uuid4().hex[:8]}_{safe_name}"
            upload_path = os.path.join(base_dir, "uploads", tmp_name)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            with open(upload_path, 'wb') as f:
                f.write(raw)

            # 验证文件有效性
            val_err = _validate_docx_file(upload_path)
            if val_err:
                return _make_error_json("INVALID_DOCX", val_err)

            # Step 2: 解析表单字段
            from docx import Document as DocxDoc
            doc = DocxDoc(upload_path)
            fields = _parse_docx_fields(doc)

            if not fields and not (fill_cells_json and fill_cells_json.strip()):
                return _make_error_json("NO_FIELDS", "未检测到待填写的空字段")

            # Step 3: 匹配并填充（复用共享逻辑）
            fill_data = json.loads(fill_data_json)
            filled_count, unmatched, pending = _do_fill_docx(
                doc, fill_data, FIELD_SYNONYMS, font_name, font_size_pt, font_color
            )

            # Step 3.5: 坐标精确填充（异形表主通道，处理合并单元格、保留格式）
            if fill_cells_json and fill_cells_json.strip():
                try:
                    cells_to_fill = json.loads(fill_cells_json)
                except json.JSONDecodeError:
                    return _make_error_json("INVALID_CELLS_JSON", "fill_cells_json 必须是合法 JSON 数组")
                if not isinstance(cells_to_fill, list):
                    return _make_error_json("INVALID_CELLS_JSON", "fill_cells_json 必须是数组")
                for item in cells_to_fill:
                    if not isinstance(item, dict):
                        continue
                    try:
                        ti = int(item.get('table_index', 0))
                        r = int(item.get('row', -1))
                        c = int(item.get('col', -1))
                    except (ValueError, TypeError):
                        continue
                    val = str(item.get('value', ''))
                    if val == '' or ti < 0 or ti >= len(doc.tables) or r < 0 or c < 0:
                        continue
                    target = _resolve_write_cell(doc.tables[ti], r, c)
                    if target is None:
                        continue
                    _fill_cell_preserving_format(target, val, font_name, font_size_pt, font_color)
                    filled_count += 1

            # Step 4: 保存填好的文件（秒级时间戳 + 冲突后缀）
            out_path = _unique_output_path(
                os.path.join(base_dir, "uploads"),
                f"{os.path.splitext(safe_name)[0]}_已填写", ".docx")
            out_filename = os.path.basename(out_path)
            doc.save(out_path)

            download_url = _make_download_url(out_path)
            result = {
                "status": "ok",
                "output_filename": out_filename,
                "total_fields": len(fields),
                "filled_count": filled_count,
                "unmatched_field_names": unmatched,
                "usage_note": "默认不返回 filled_base64（节省Token）。如需下载请使用 download_url。",
            }
            if pending:
                result["pending_fields"] = pending
            if download_url:
                result["download_url"] = download_url

            # 仅在显式要求时返回 Base64（避免大量 Token 消耗）
            if return_base64:
                with open(out_path, 'rb') as f:
                    result["filled_base64"] = base64.b64encode(f.read()).decode('ascii')

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return _make_error_json("FILL_ERROR", str(e))
        finally:
            _cleanup_temp_file(upload_path)

    # =====================================================================
    # 共享核心：_smart_fill_core — smart_fill_form / smart_fill_form_local 共用
    # =====================================================================
    async def _smart_fill_core(
        doc,
        filename: str,
        knowledge_data: str,
        personal_file_path: str,
        personal_text: str,
        font_name: str,
        font_size_pt: float,
        font_color: str,
        preview_only: bool,
        return_base64: bool,
    ) -> str:
        """smart_fill_form 与 smart_fill_form_local 的共享核心逻辑。"""
        # 解析表单字段
        form_fields = _parse_docx_fields(doc)
        seen = set()
        unique_fields = []
        for f in form_fields:
            norm = _normalize_field_name(f)
            if norm not in seen:
                seen.add(norm)
                unique_fields.append(f)

        if not unique_fields:
            return _make_error_json("NO_FIELDS", "未检测到待填写的空字段")

        # 收集个人信息（按优先级合并）
        sources = []
        source_log = []

        if knowledge_data and knowledge_data.strip():
            try:
                kb_json = json.loads(knowledge_data)
                flat = _flatten_person_info(kb_json)
                if flat:
                    sources.append(flat)
                    source_log.append("knowledge_data(JSON)")
            except json.JSONDecodeError:
                parsed_text = await read_personal_info_from_text(knowledge_data)
                parsed_data = json.loads(parsed_text)
                flat = _flatten_person_info(parsed_data)
                if flat:
                    sources.append(flat)
                    source_log.append("knowledge_data(text)")

        if personal_file_path and personal_file_path.strip():
            try:
                parsed_file = await read_personal_info_from_file(personal_file_path)
                parsed_data = json.loads(parsed_file)
                flat = _flatten_person_info(parsed_data)
                if flat:
                    sources.append(flat)
                    source_log.append("personal_file")
            except Exception:
                pass

        if personal_text and personal_text.strip():
            try:
                parsed_text = await read_personal_info_from_text(personal_text)
                parsed_data = json.loads(parsed_text)
                flat = _flatten_person_info(parsed_data)
                if flat:
                    sources.append(flat)
                    source_log.append("personal_text")
            except Exception:
                pass

        # 合并多源信息
        merged_info = {}
        for s in sources:
            for k, v in s.items():
                if v and v != "【待补充】":
                    merged_info[k] = v

        fill_data = [{"field_name": k, "value": v} for k, v in merged_info.items()]

        if not fill_data and not preview_only:
            return _make_error_json(
                "NO_DATA",
                "未从任何信息源中提取到有效个人信息。请提供 knowledge_data、personal_file_path 或 personal_text 之一。"
            )

        # preview_only 模式
        if preview_only:
            fill_map = {f['field_name']: f['value'] for f in fill_data}
            normalized_map = _build_normalized_map(fill_data)
            match_cache = {}
            matched_count = 0
            match_preview = []

            for field in unique_fields:
                v = _match_field_value(field, fill_map, normalized_map, FIELD_SYNONYMS, match_cache)
                if v:
                    matched_count += 1
                    match_preview.append({"field": field, "value": v, "status": "matched"})
                else:
                    match_preview.append({"field": field, "value": None, "status": "unmatched"})

            result = {
                "status": "ok",
                "mode": "preview",
                "filename": filename,
                "total_fields": len(unique_fields),
                "matched_count": matched_count,
                "unmatched_count": len(unique_fields) - matched_count,
                "source_log": source_log,
                "field_preview": match_preview,
                "fill_data": fill_data,
                "usage": "确认后，再次调用 smart_fill_form / smart_fill_form_local 并将 preview_only 设为 false 完成填表",
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        # 填充
        filled_count, unmatched, pending = _do_fill_docx(
            doc, fill_data, FIELD_SYNONYMS, font_name, font_size_pt, font_color
        )

        # 保存并返回（秒级时间戳 + 冲突后缀）
        out_path = _unique_output_path(
            os.path.join(base_dir, "uploads"),
            f"{os.path.splitext(filename)[0]}_已填写", ".docx")
        out_filename = os.path.basename(out_path)
        doc.save(out_path)

        download_url = _make_download_url(out_path)
        result = {
            "status": "ok",
            "mode": "filled",
            "output_filename": out_filename,
            "total_fields": len(unique_fields),
            "filled_count": filled_count,
            "unmatched_field_names": unmatched,
            "source_log": source_log,
            "usage_note": "默认不返回 filled_base64（节省Token）。如需下载请使用 download_url。",
        }
        if pending:
            result["pending_fields"] = pending
        if download_url:
            result["download_url"] = download_url
        if return_base64:
            with open(out_path, 'rb') as f:
                result["filled_base64"] = base64.b64encode(f.read()).decode('ascii')

        return json.dumps(result, ensure_ascii=False, indent=2)

    # =====================================================================
    # 工具7b: smart_fill_form — 一站式智能填表（Base64 入口）
    # =====================================================================
    @mcp.tool()
    async def smart_fill_form(
        file_base64: str,
        filename: str = "document.docx",
        knowledge_data: str = "",
        personal_file_path: str = "",
        personal_text: str = "",
        font_name: str = "宋体",
        font_size_pt: float = 12.0,
        font_color: str = "000000",
        preview_only: bool = False,
        return_base64: bool = False,
    ) -> str:
        """一站式智能填表（Base64 入口）：上传空表 + 提供信息源 → 自动解析、匹配、填充、返回结果。

将原本需要 LLM 多次编排的 3~5 次工具调用合并为 1 次。

Args:
    file_base64: Word 空表的 Base64 编码字符串
    filename: 文档文件名（如 "个人简历空表.docx"）
    knowledge_data: 知识库检索结果（JSON 字符串或自然语言文本），优先级最高
    personal_file_path: 个人信息文件路径（.json/.txt/.docx/.xlsx），次优先级
    personal_text: 自然语言描述的个人信息，最低优先级
    font_name: 填充字体，默认 "宋体"
    font_size_pt: 字号（磅），默认 12.0
    font_color: 字体颜色，默认 "0000FF"
    preview_only: 仅预览模式（默认 False）。为 True 时只解析字段、不填充。
    return_base64: 是否返回 filled_base64（默认 False，节省 Token）

Returns:
    JSON，包含 download_url、filled_count、total_fields 等
"""
        upload_path = None
        try:
            size_err = _check_base64_size(file_base64)
            if size_err:
                return _make_error_json("FILE_TOO_LARGE", size_err)

            raw = base64.b64decode(file_base64)
            safe_name = os.path.basename(filename)
            if not safe_name.lower().endswith('.docx'):
                safe_name += '.docx'
            tmp_name = f"tmp_{uuid.uuid4().hex[:8]}_{safe_name}"
            upload_path = os.path.join(base_dir, "uploads", tmp_name)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            with open(upload_path, 'wb') as f:
                f.write(raw)

            val_err = _validate_docx_file(upload_path)
            if val_err:
                return _make_error_json("INVALID_DOCX", val_err)

            from docx import Document as DocxDoc
            doc = DocxDoc(upload_path)

            return await _smart_fill_core(
                doc, safe_name, knowledge_data, personal_file_path, personal_text,
                font_name, font_size_pt, font_color, preview_only, return_base64,
            )
        except Exception as e:
            return _make_error_json("SMART_FILL_ERROR", str(e))
        finally:
            _cleanup_temp_file(upload_path)

    # =====================================================================
    # 工具7c: smart_fill_form_local — 一站式智能填表（本地路径入口，无大小限制）
    # =====================================================================
    @mcp.tool()
    async def smart_fill_form_local(
        docx_path: str,
        knowledge_data: str = "",
        personal_file_path: str = "",
        personal_text: str = "",
        font_name: str = "宋体",
        font_size_pt: float = 12.0,
        font_color: str = "000000",
        preview_only: bool = False,
    ) -> str:
        """一站式智能填表（本地路径入口）：平台已上传文件到服务器，直接读取路径填表。

无 Base64 大小限制，不消耗 LLM Token，效率最高。推荐平台先调用 file_upload 上传文件，
再将返回的 server_path 传入此工具。

Args:
    docx_path: 服务器上的 Word 文档路径，如 "/data/uploads/空表.docx"
    knowledge_data: 知识库检索结果（JSON 字符串或自然语言文本），优先级最高
    personal_file_path: 个人信息文件路径，次优先级
    personal_text: 自然语言描述的个人信息，最低优先级
    font_name: 填充字体，默认 "宋体"
    font_size_pt: 字号（磅），默认 12.0
    font_color: 字体颜色，默认 "0000FF"
    preview_only: 仅预览模式（默认 False）

Returns:
    JSON，包含 download_url、filled_count、total_fields 等
"""
        try:
            safe_path = _resolve_read_path(docx_path)
            if not safe_path.lower().endswith('.docx'):
                return _make_error_json("INVALID_FILE", f"必须是 .docx 文件: {safe_path}")

            val_err = _validate_docx_file(safe_path)
            if val_err:
                return _make_error_json("INVALID_DOCX", val_err)

            from docx import Document as DocxDoc
            doc = DocxDoc(safe_path)
            filename = os.path.basename(safe_path)

            return await _smart_fill_core(
                doc, filename, knowledge_data, personal_file_path, personal_text,
                font_name, font_size_pt, font_color, preview_only, False,
            )
        except Exception as e:
            return _make_error_json("SMART_FILL_LOCAL_ERROR", str(e))

    # =====================================================================
    # 工具5: parse_word_form
    # =====================================================================
    @mcp.tool()
    async def parse_word_form(docx_path: str) -> str:
        """
        解析 Word 表单文档，提取所有待填写的字段信息

        Args:
            docx_path: Word 文档的完整路径，如 C:\\Users\\lx\\Downloads\\个人简历空表.docx。
                       请务必传入完整绝对路径，不要只传文件名。

        Returns:
            JSON 字符串，包含所有待填写字段列表
        """
        try:
            from docx import Document
        except ImportError:
            return "Error: 请安装 python-docx (pip install python-docx)"

        try:
            safe_path = _resolve_read_path(docx_path)
        except (ValueError, OSError) as e:
            return _make_error_json("FILE_NOT_FOUND", str(e))
        if not safe_path.lower().endswith('.docx'):
            return _make_error_json(
                "INVALID_FILE", f"parse_word_form 仅支持 .docx 文件，收到: {safe_path}")

        try:
            doc = Document(safe_path)
        except Exception as e:
            return _make_error_json(
                "INVALID_DOCX", f"无法解析 Word 文档（文件可能已损坏或不是 docx）: {e}")
        fields = []

        # 提取段落中的字段（正文 + 页眉页脚 + 文本框，支持同段多占位）
        # 仅识别有明确占位信号的行（冒号/下划线/大段空白），不再把任意纯文本
        # 段落当作字段名，避免标题（"人员登记表"）被误报为待填字段。
        for i, para in enumerate(_iter_story_paragraphs(doc)):
            raw_text = para.text
            text = raw_text.strip()
            if not text:
                continue
            for name in _extract_para_field_names(raw_text):
                fields.append({
                    'type': 'paragraph',
                    'field_name': name,
                    'index': i,
                    'text': text
                })

        # 提取表格字段（支持合并单元格 + 嵌套表 + 标签下划线同格）
        # 注意：不按 _tc 去重，因为纵向合并的空值单元格在视觉上属于多行，
        # 每行有独立的左侧字段名（如 R0C1 对应"姓名"，R1C1 对应"出生年月"）
        for ti, table in enumerate(doc.tables):
            for tbl, ri, ci, cell, has_nested, nested in _iter_table_cells(table):
                if has_nested:
                    continue  # 嵌套表容器格，字段由子表递归产出
                text = cell.text.strip()
                if not _is_empty_cell(text):
                    # 非空但含内联占位（"姓名：____"）：按内联字段上报
                    if _has_inline_placeholder(text):
                        for name in _extract_para_field_names(cell.text):
                            item = {
                                'type': 'table_cell_inline',
                                'field_name': name,
                                'table_index': ti,
                                'row_index': ri,
                                'cell_index': ci,
                            }
                            if nested:
                                item['nested_table'] = True
                            fields.append(item)
                    continue  # 其余非空单元格是字段名，跳过

                field_name = None
                # 优先检查左侧单元格
                if ci > 0:
                    for left_ci in range(ci - 1, -1, -1):
                        left_cell = tbl.rows[ri].cells[left_ci]
                        left = left_cell.text.strip()
                        if left and not _is_empty_cell(left):
                            field_name = left
                            break

                # 其次检查上方单元格（用于纵向标题行的情况）
                if not field_name and ri > 0:
                    for up_ri in range(ri - 1, -1, -1):
                        above_cell = tbl.rows[up_ri].cells[ci]
                        above = above_cell.text.strip()
                        if above and not _is_empty_cell(above):
                            field_name = above
                            break

                if field_name:
                    item = {
                        'type': 'table_cell',
                        'field_name': field_name,
                        'table_index': ti,
                        'row_index': ri,
                        'cell_index': ci
                    }
                    if nested:
                        item['nested_table'] = True
                    fields.append(item)

        # 输出结构化结果：字段列表 + 各表格逻辑网格 + 布局复杂度（供 LLM 坐标映射通道使用）
        result = {
            "status": "ok",
            "filename": os.path.basename(safe_path),
            "total_fields": len(fields),
            "fields": fields,
            "tables": [
                {"table_index": ti, "rows": _build_table_grid(t)}
                for ti, t in enumerate(doc.tables)
            ],
            "layout": _analyze_layout_complexity(doc),
            "usage": (
                "若 layout.confidence 为 low（存在合并单元格/嵌套表/标签+下划线同格），"
                "MCP 自动推断可能漏填或填错。请基于 tables 网格逐格判断，输出坐标映射："
                "[{\"table_index\":0, \"row\":2, \"col\":3, \"value\":\"张三\"}]，"
                "再调用 fill_word_form(fill_cells_json=...) 按坐标精确填充。"
            ),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # =====================================================================
    # 工具5b: parse_word_form_base64 — 解析 Base64 Word 文档字段
    # =====================================================================
    @mcp.tool()
    async def parse_word_form_base64(
        file_base64: str,
        filename: str = "document.docx",
    ) -> str:
        """解析 Base64 编码的 Word 表单文档，提取所有待填写的字段信息。

用于远程场景：用户上传空表后，先预览有哪些字段需要填写，再决定填充数据。

Args:
    file_base64: Word 文档的 Base64 编码字符串
    filename: 文档文件名（如 "个人简历空表.docx"），默认 document.docx

Returns:
    JSON，包含所有待填写字段列表（格式同 parse_word_form）
"""
        upload_path = None
        try:
            # 检查文件大小
            size_err = _check_base64_size(file_base64)
            if size_err:
                return _make_error_json("FILE_TOO_LARGE", size_err)

            raw = base64.b64decode(file_base64)
            safe_name = os.path.basename(filename)
            if not safe_name.lower().endswith('.docx'):
                safe_name += '.docx'
            tmp_name = f"tmp_{uuid.uuid4().hex[:8]}_{safe_name}"
            upload_path = os.path.join(base_dir, "uploads", tmp_name)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            with open(upload_path, 'wb') as f:
                f.write(raw)

            val_err = _validate_docx_file(upload_path)
            if val_err:
                return _make_error_json("INVALID_DOCX", val_err)

            from docx import Document as DocxDoc
            doc = DocxDoc(upload_path)
            form_fields = _parse_docx_fields(doc)

            # 去重但保留顺序
            seen = set()
            unique_fields = []
            for f in form_fields:
                norm = _normalize_field_name(f)
                if norm not in seen:
                    seen.add(norm)
                    unique_fields.append(f)

            result = {
                "status": "ok",
                "filename": safe_name,
                "total_fields": len(unique_fields),
                "fields": unique_fields,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return _make_error_json("PARSE_ERROR", str(e))
        finally:
            _cleanup_temp_file(upload_path)

    # =====================================================================
    # 工具6: fill_word_form
    # =====================================================================
    @mcp.tool()
    async def fill_word_form(
        docx_path: str,
        output_file: str,
        fill_data_json: str = "[]",
        fill_cells_json: str = "",
        font_name: str = "宋体",
        font_size_pt: float = 12.0,
        font_color: str = "000000",
        verbose: bool = False
    ) -> str:
        """
        根据填充数据填写 Word 表单，生成新文档

        Args:
            docx_path: 原始 Word 文档(.docx)的完整路径，与 parse_word_form 的 docx_path 一致
            output_file: 填写后输出文件的完整路径，如 C:\\Users\\lx\\Downloads\\个人简历已填写.docx
            fill_data_json: 填充数据 JSON 字符串，格式:
                [{"field_name": "姓名", "value": "张三"}, {"field_name": "性别", "value": "男"}]
                其中 field_name 必须与 parse_word_form 返回的字段名一致
            fill_cells_json: （推荐，适用于异形表）按坐标精确填充的 JSON 字符串，格式:
                [{"table_index": 0, "row": 2, "col": 3, "value": "张三"}, ...]
                坐标来自 parse_word_form 返回的 tables 网格（row/col 为逻辑坐标，
                自动处理合并单元格）。与 fill_data_json 可同时使用：先做字段匹配填充，
                再按坐标覆盖/补齐；坐标填充优先级更高，不依赖左/上推断。
            font_name: 填充文字的字体，默认"宋体"
            font_size_pt: 填充文字的字号(磅)，默认12(即小四)
            font_color: 填充文字的字体颜色，默认"000000"（黑色）
                支持格式:
                - 自然语言: "红色", "蓝色", "黑色", "绿色"
                - 16进制: "FF0000", "#FF0000", "0000FF", "#0000FF"
                常用颜色: "000000"/"黑色"=黑色, "FF0000"/"红色"=红色, "00FF00"/"绿色"=绿色, "0000FF"/"蓝色"=蓝色
                注意：实际填充优先保留模板单元格原有格式（就地替换占位 run），
                此参数仅在单元格无参考格式时生效
            verbose: 是否返回详细填充信息（fill_details/unmatched_fields），默认 False 减少 JSON 体积

        Returns:
            操作结果信息
        """
        try:
            from docx import Document
            from docx.shared import Pt, RGBColor
        except ImportError:
            return _make_error_json("DEPENDENCY_MISSING", "请安装 python-docx (pip install python-docx)")

        try:
            safe_input = _resolve_read_path(docx_path)
        except (ValueError, OSError) as e:
            return _make_error_json("FILE_NOT_FOUND", str(e))
        if not safe_input.lower().endswith('.docx'):
            return _make_error_json("INVALID_FILE", f"docx_path 必须是 .docx 文件，收到: {safe_input}")

        # 自动在输出文件名中插入秒级时间戳（同秒同名时追加短 uuid，避免静默覆盖）
        base, ext = os.path.splitext(output_file)
        if ext.lower() != '.docx':
            ext = '.docx'
        target = _resolve_write_path(output_file)
        abs_output = _unique_output_path(
            os.path.dirname(target), os.path.splitext(os.path.basename(target))[0], ext)

        try:
            fill_data = json.loads(fill_data_json)
        except json.JSONDecodeError as e:
            return _make_error_json(
                "INVALID_ARGUMENT", f"fill_data_json 不是合法 JSON: {e}")
        if not isinstance(fill_data, list):
            return _make_error_json(
                "INVALID_ARGUMENT", "fill_data_json 必须是数组，如 [{\"field_name\": \"姓名\", \"value\": \"张三\"}]")
        fill_map = {f['field_name']: f['value'] for f in fill_data}

        # =====================================================================
        # 预构建匹配数据：避免循环内重复计算
        # =====================================================================
        # 规范化映射: 去空格后的字段名 -> value
        normalized_map = {}
        for f in fill_data:
            norm = _normalize_field_name(f['field_name'])
            normalized_map[norm] = f['value']
            normalized_map[f['field_name']] = f['value']

        # 预编译所有正则模式（与 _do_fill_docx 共用同一套构建逻辑）
        # 同时收集原始字段名和同义词，以便匹配表单中的各种变体（如"学历/学位"）
        para_patterns = _build_para_patterns(fill_data, FIELD_SYNONYMS)
        inline_patterns = _build_para_patterns(fill_data, FIELD_SYNONYMS, inline=True)

        # 缓存 _match_field 结果
        _match_cache = {}

        def _match_field_cached(cell_text: str) -> str | None:
            """带缓存的模糊匹配，支持同义词映射和分词匹配"""
            if cell_text in _match_cache:
                return _match_cache[cell_text]
            text = cell_text.strip()
            # 1. 精确匹配
            if text in fill_map:
                result = fill_map[text]
                _match_cache[cell_text] = result
                return result
            # 2. 规范化匹配
            norm = _normalize_field_name(text)
            if norm in normalized_map:
                result = normalized_map[norm]
                _match_cache[cell_text] = result
                return result
            # 3. 同义词映射匹配
            if norm in FIELD_SYNONYMS:
                standard_name = FIELD_SYNONYMS[norm]
                # 在 fill_map 中查找标准名称
                for key, val in fill_map.items():
                    if _normalize_field_name(key) == standard_name:
                        _match_cache[cell_text] = val
                        return val
            # 4. 分词匹配（处理"学历/学位"这类复合字段）
            parts = re.split(r'[\s/\\|（）()【】\[\]、,\-_.~!@#$%^&*+=?<>"\'\`]+', text)
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if part in fill_map:
                    _match_cache[cell_text] = fill_map[part]
                    return fill_map[part]
                part_norm = _normalize_field_name(part)
                if part_norm in normalized_map:
                    _match_cache[cell_text] = normalized_map[part_norm]
                    return normalized_map[part_norm]
                if part_norm in FIELD_SYNONYMS:
                    standard_name = FIELD_SYNONYMS[part_norm]
                    for key, val in fill_map.items():
                        if _normalize_field_name(key) == standard_name:
                            _match_cache[cell_text] = val
                            return val
            # 5. 包含匹配（兜底）
            for key, val in fill_map.items():
                norm_key = _normalize_field_name(key)
                if norm_key in norm or norm in norm_key:
                    _match_cache[cell_text] = val
                    return val
            _match_cache[cell_text] = None
            return None

        try:
            doc = Document(safe_input)
        except Exception as e:
            return _make_error_json(
                "INVALID_DOCX", f"无法解析 Word 文档（文件可能已损坏或不是 docx）: {e}")
        filled_count = 0
        fill_details = []
        unmatched_fields = []
        used_field_names = set()
        start_time = time.time()

        def _apply_fill_font(run):
            """为填充的 run 应用默认字体和颜色"""
            run.font.name = font_name
            from docx.oxml.ns import qn
            rPr = run._element.get_or_add_rPr()
            rFonts = rPr.find(qn('w:rFonts'))
            if rFonts is None:
                from docx.oxml import OxmlElement
                rFonts = OxmlElement('w:rFonts')
                rPr.insert(0, rFonts)
            rFonts.set(qn('w:eastAsia'), font_name)
            run.font.size = Pt(font_size_pt)
            # 解析颜色：支持自然语言和16进制
            COLOR_MAP = {
                '黑色': '000000', '黑': '000000',
                '红色': 'FF0000', '红': 'FF0000',
                '绿色': '00FF00', '绿': '00FF00',
                '蓝色': '0000FF', '蓝': '0000FF',
                '黄色': 'FFFF00', '黄': 'FFFF00',
                '紫色': '800080', '紫': '800080',
                '橙色': 'FFA500', '橙': 'FFA500',
                '白色': 'FFFFFF', '白': 'FFFFFF',
                '灰色': '808080', '灰': '808080',
                '粉色': 'FFC0CB', '粉': 'FFC0CB',
                '棕色': 'A52A2A', '棕': 'A52A2A',
            }
            try:
                color_input = font_color.strip().lower()
                # 自然语言映射
                if color_input in COLOR_MAP:
                    color_hex = COLOR_MAP[color_input]
                else:
                    color_hex = font_color.lstrip('#').upper()
                if len(color_hex) == 6:
                    r = int(color_hex[0:2], 16)
                    g = int(color_hex[2:4], 16)
                    b = int(color_hex[4:6], 16)
                    run.font.color.rgb = RGBColor(r, g, b)
                else:
                    run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
            except (ValueError, AttributeError):
                run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

        # =====================================================================
        # 填充段落：正文 + 页眉页脚 + 文本框（与 _do_fill_docx 一致）
        # =====================================================================
        field_filter_re = _build_field_filter(fill_data, FIELD_SYNONYMS)

        for para in _iter_story_paragraphs(doc):
            full_text = para.text
            if not full_text.strip():
                continue
            # 快速过滤：标签可能被空格拆开（"姓 名"），同时比对去空白文本
            if not _para_matches_filter(full_text, field_filter_re):
                continue
            # 必须有占位符才处理（含全角下划线 ＿）
            if not _has_placeholder(full_text):
                continue

            # 不 break：同一段落中的多个占位符一次性全部替换
            new_text, matched_fields = _apply_para_replacements(full_text, para_patterns)
            if new_text == full_text or not matched_fields:
                continue
            # 格式保持：重建段落但保留原段落首个 run 的格式（无则继承文档默认）
            _fill_para_preserving_format(para, new_text)
            for fn, n in matched_fields:
                filled_count += n
                used_field_names.add(fn)
                fill_details.append({
                    "field": fn, "value": fill_map.get(fn, ""),
                    "location": "paragraph", "status": "filled"
                })

        # =====================================================================
        # 填充表格：支持合并单元格 + 嵌套表 + 标签下划线同格 + 缓存匹配
        # 注意：不按 _tc 去重，纵向合并的空值单元格每行有独立的左侧字段名
        # =====================================================================
        for table in doc.tables:
            for tbl, ri, ci, cell, has_nested, _nested in _iter_table_cells(table):
                if has_nested:
                    continue  # 嵌套表容器格由递归子表处理
                cell_text = cell.text.strip()
                if not _is_empty_cell(cell_text):
                    # 非空单元格：仅处理内联占位（如「姓名：____ 电话：＿＿＿＿」）
                    if _has_inline_placeholder(cell_text):
                        n, hits = _fill_placeholder_paragraphs(cell.paragraphs, inline_patterns)
                        if n:
                            filled_count += n
                            used_field_names.update(fn for fn, _cnt in hits)
                            for fn, cnt in hits:
                                fill_details.append({
                                    "field": fn, "value": fill_map.get(fn, ""),
                                    "location": f"table[row={ri},col={ci}]",
                                    "status": "filled", "count": cnt
                                })
                    continue

                fill_value = None
                matched_field = None

                # 方向1: 左侧单元格
                if ci > 0:
                    for left_ci in range(ci - 1, -1, -1):
                        left_cell = tbl.rows[ri].cells[left_ci]
                        left_text = left_cell.text.strip()
                        if left_text and not _is_empty_cell(left_text):
                            fill_value = _match_field_cached(left_text)
                            if fill_value:
                                matched_field = left_text
                                break

                # 方向2: 上方单元格
                if not fill_value and ri > 0:
                    for up_ri in range(ri - 1, -1, -1):
                        above_cell = tbl.rows[up_ri].cells[ci]
                        above_text = above_cell.text.strip()
                        if above_text and not _is_empty_cell(above_text):
                            fill_value = _match_field_cached(above_text)
                            if fill_value:
                                matched_field = above_text
                                break

                if fill_value:
                    # 格式保持：就地替换占位 run / 复制单元格内参考 run 格式 / 继承文档默认
                    _fill_cell_preserving_format(cell, fill_value, font_name, font_size_pt, font_color)
                    filled_count += 1
                    # 通过 matched_field 反查原始 field_name
                    if matched_field:
                        # 先精确匹配
                        if matched_field in fill_map:
                            used_field_names.add(matched_field)
                        else:
                            # 规范化匹配
                            norm_matched = _normalize_field_name(matched_field)
                            for fn in fill_map:
                                if _normalize_field_name(fn) == norm_matched:
                                    used_field_names.add(fn)
                                    break
                            else:
                                # 同义词映射匹配
                                if norm_matched in FIELD_SYNONYMS:
                                    standard = FIELD_SYNONYMS[norm_matched]
                                    for fn in fill_map:
                                        if _normalize_field_name(fn) == standard:
                                            used_field_names.add(fn)
                                            break
                    fill_details.append({
                        "field": matched_field, "value": fill_value,
                        "location": f"table[row={ri},col={ci}]", "status": "filled"
                    })

        # =====================================================================
        # 坐标精确填充（fill_cells_json）——异形表主通道
        # 格式: [{"table_index":0, "row":2, "col":3, "value":"张三", "field":"姓名"}, ...]
        # 坐标来自 parse_word_form 返回的 tables 网格；自动处理纵向合并；格式保持
        # =====================================================================
        if fill_cells_json and fill_cells_json.strip():
            try:
                cells_to_fill = json.loads(fill_cells_json)
            except json.JSONDecodeError:
                return _make_error_json("INVALID_CELLS_JSON", "fill_cells_json 必须是合法 JSON 数组")
            if not isinstance(cells_to_fill, list):
                return _make_error_json("INVALID_CELLS_JSON", "fill_cells_json 必须是数组")
            for item in cells_to_fill:
                if not isinstance(item, dict):
                    continue
                try:
                    ti = int(item.get('table_index', 0))
                    r = int(item.get('row', -1))
                    c = int(item.get('col', -1))
                except (ValueError, TypeError):
                    continue
                val = str(item.get('value', ''))
                cell_field = item.get('field') or f"t{ti}r{r}c{c}"
                if val == '' or ti < 0 or ti >= len(doc.tables) or r < 0 or c < 0:
                    fill_details.append({
                        "field": cell_field, "value": val,
                        "location": f"table[row={r},col={c}]", "status": "skipped_invalid_coord"
                    })
                    continue
                table = doc.tables[ti]
                target = _resolve_write_cell(table, r, c)
                if target is None:
                    fill_details.append({
                        "field": cell_field, "value": val,
                        "location": f"table[row={r},col={c}]", "status": "skipped_invalid_coord"
                    })
                    continue
                _fill_cell_preserving_format(target, val, font_name, font_size_pt, font_color)
                filled_count += 1
                used_field_names.add(cell_field)
                fill_details.append({
                    "field": cell_field, "value": val,
                    "location": f"table[row={r},col={c}]", "status": "filled"
                })

        # 记录未匹配的字段
        for field_name, value in fill_map.items():
            if field_name not in used_field_names:
                unmatched_fields.append({"field_name": field_name, "value": value})

        elapsed = round(time.time() - start_time, 3)

        # 确保输出目录存在
        os.makedirs(os.path.dirname(abs_output), exist_ok=True)
        doc.save(abs_output)

        # 生成 file:// 链接（Windows 路径需要处理反斜杠和空格）
        # 将反斜杠替换为正斜杠，并对特殊字符进行 URL 编码
        import urllib.parse
        file_url = abs_output.replace('\\', '/')
        file_url = urllib.parse.quote(file_url, safe='/:@')
        if not file_url.startswith('/'):
            file_url = '/' + file_url
        file_link = f"file://{file_url}"

        result = {
            "status": "ok",
            "output_path": abs_output,
            "output_link": file_link,
            "filled_count": filled_count,
            "total_fields": len(fill_data),
            "elapsed_seconds": elapsed,
            "font": font_name,
            "font_size_pt": font_size_pt,
            "font_color": font_color,
        }
        if verbose:
            result["fill_details"] = fill_details
            result["unmatched_fields"] = unmatched_fields
        else:
            # 精简模式：只返回未匹配字段的 field_name 列表
            result["unmatched_field_names"] = [u["field_name"] for u in unmatched_fields]

        # 收集值为 "【待补充】" 的字段（字段名匹配成功但知识库缺数据）
        pending_fields = [fn for fn, val in fill_map.items() if val == "【待补充】"]
        if pending_fields:
            result["pending_fields"] = pending_fields

        # 自动用系统默认程序打开生成的文档
        try:
            if sys.platform == "win32":
                # 使用 start 命令，通过 shell 启动，确保与桌面交互
                import subprocess
                subprocess.Popen(
                    ['start', '', abs_output],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", abs_output], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", abs_output], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result["auto_opened"] = True
        except Exception as e:
            result["auto_opened"] = False
            result["auto_open_error"] = str(e)

        # 如果文件在 base_dir 下，提供 HTTP 下载链接（远程部署时使用）
        download_url = _make_download_url(abs_output)
        if download_url:
            result["download_url"] = download_url

        return json.dumps(result, ensure_ascii=False, indent=2)
