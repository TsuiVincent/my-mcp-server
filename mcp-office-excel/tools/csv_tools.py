"""
CSV 工具模块

提供 CSV 文件的结构化读写能力，纯 Python 标准库实现。

工具列表:
- csv_read          读取 CSV 为结构化数据
- csv_write          写入 CSV（列表或字典）
- csv_analyze        分析 CSV（行数、列名、类型推断、空值统计）
- csv_query          简单查询过滤
"""

import os
import json
import csv
from mcp.server.fastmcp import FastMCP


def _resolve_safe_path(path: str, base_dir: str) -> str:
    if os.path.isabs(path):
        if not path.startswith(os.path.abspath(base_dir)):
            raise ValueError(f"路径越权: {path}")
        return path
    return os.path.join(base_dir, path)


def _detect_delimiter(sample: str) -> str:
    """自动检测 CSV 分隔符"""
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample)
        return dialect.delimiter
    except csv.Error:
        # 回退：统计常见分隔符出现次数
        candidates = {',': 0, '\t': 0, ';': 0, '|': 0}
        for line in sample.split('\n')[:5]:
            for ch in candidates:
                candidates[ch] += line.count(ch)
        return max(candidates, key=candidates.get)


def register_csv_tools(mcp: FastMCP, base_dir: str = "/data", **kwargs):
    """注册 CSV 工具"""

    # ==========================================
    # 读取
    # ==========================================

    @mcp.tool()
    async def csv_read(
        path: str,
        encoding: str = "utf-8-sig",
        delimiter: str = "auto",
        max_rows: int = 1000,
        has_header: bool = True,
    ) -> str:
        """读取 CSV 文件，返回结构化 JSON（含 headers 和 data）。

        Args:
            path: CSV 文件路径
            encoding: 文件编码，默认 utf-8-sig（兼容 Excel 导出的 BOM CSV）
            delimiter: 分隔符，"auto" 自动检测，或显式指定如 "," / "\\t" / ";" / "|"
            max_rows: 最大读取行数，默认 1000
            has_header: 第一行是否为表头，默认 True

        Returns:
            JSON: {"status":"ok", "headers":[...], "data":[[...]], "row_count":N, "delimiter":"..."}
        """
        try:
            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            with open(target, 'r', encoding=encoding, errors='replace') as f:
                sample = f.read(4096)
                delim = delimiter if delimiter != "auto" else _detect_delimiter(sample)

            with open(target, 'r', encoding=encoding, errors='replace') as f:
                reader = csv.reader(f, delimiter=delim)

                headers = []
                data = []
                row_count = 0

                for i, row in enumerate(reader):
                    if i == 0 and has_header:
                        headers = row
                        continue
                    if row_count >= max_rows:
                        break
                    data.append(row)
                    row_count += 1

            return json.dumps({
                "status": "ok",
                "file": path,
                "delimiter": delim,
                "encoding": encoding,
                "headers": headers,
                "row_count": row_count,
                "column_count": len(headers) if headers else (len(data[0]) if data else 0),
                "data": data,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 写入
    # ==========================================

    @mcp.tool()
    async def csv_write(
        path: str,
        data: str,
        headers: str = "",
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        append: bool = False,
    ) -> str:
        """将结构化数据写入 CSV 文件。

        data 接受两种 JSON 格式:
        1. 列表的列表: [["col1","col2"],["val1","val2"]]
        2. 字典列表: [{"name":"张三","age":30}, ...]  —— 需同时传 headers

        Args:
            path: CSV 文件路径
            data: JSON 字符串，二维数组或字典列表
            headers: JSON 数组 '["列1","列2"]'，字典格式时必须提供
            delimiter: 分隔符，默认 ","
            encoding: 输出编码，默认 utf-8-sig（Excel 兼容）
            append: 是否追加模式，默认 False

        Returns:
            JSON: {"status":"ok", "rows_written":N, "file":"..."}
        """
        try:
            target = _resolve_safe_path(path, base_dir)
            os.makedirs(os.path.dirname(target), exist_ok=True)

            parsed = json.loads(data)
            if not isinstance(parsed, list) or len(parsed) == 0:
                return json.dumps({"error": "data 必须是非空 JSON 数组"}, ensure_ascii=False)

            header_list = json.loads(headers) if headers else []

            mode = 'a' if append else 'w'

            with open(target, mode, encoding=encoding, newline='') as f:
                writer = csv.writer(f, delimiter=delimiter)

                # 非追加模式且提供了 headers
                if not append and header_list:
                    writer.writerow(header_list)

                if isinstance(parsed[0], dict):
                    # 字典列表
                    keys = header_list if header_list else list(parsed[0].keys())
                    if not append and not header_list:
                        writer.writerow(keys)
                    for item in parsed:
                        writer.writerow([item.get(k, "") for k in keys])
                else:
                    # 列表的列表
                    for row in parsed:
                        if isinstance(row, list):
                            writer.writerow(row)
                        else:
                            writer.writerow([row])

            return json.dumps({
                "status": "ok",
                "file": path,
                "rows_written": len(parsed),
                "delimiter": delimiter,
                "encoding": encoding,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ==========================================
    # 分析
    # ==========================================

    @mcp.tool()
    async def csv_analyze(path: str, encoding: str = "utf-8-sig") -> str:
        """分析 CSV 文件：列名、数据类型推断、空值统计、行数。

        Args:
            path: CSV 文件路径
            encoding: 编码，默认 utf-8-sig

        Returns:
            JSON: {"status":"ok", "file":"...", "row_count":N, "columns":[...]}
            每个列: {"name","type","non_null_count","null_count","sample_values"}
        """
        try:
            target = _resolve_safe_path(path, base_dir)
            if not os.path.exists(target):
                return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)

            with open(target, 'r', encoding=encoding, errors='replace') as f:
                sample = f.read(4096)
                delim = _detect_delimiter(sample)

            with open(target, 'r', encoding=encoding, errors='replace') as f:
                reader = csv.reader(f, delimiter=delim)
                headers = next(reader)

                # 收集统计
                col_data = {h: [] for h in headers}
                row_count = 0
                for row in reader:
                    row_count += 1
                    for i, h in enumerate(headers):
                        val = row[i] if i < len(row) else None
                        col_data[h].append(val)

            columns = []
            for h in headers:
                vals = col_data[h]
                non_null = [v for v in vals if v is not None and v.strip() != '']
                null_count = len(vals) - len(non_null)

                # 类型推断
                col_type = "string"
                if non_null:
                    int_count = sum(1 for v in non_null if v.strip().lstrip('-').isdigit())
                    float_count = sum(1 for v in non_null if v.strip().replace('.', '', 1).replace('-', '', 1).isdigit())
                    if int_count == len(non_null):
                        col_type = "integer"
                    elif float_count > len(non_null) * 0.8:
                        col_type = "float"

                # 样本值（去重取前5）
                samples = list(dict.fromkeys(non_null[:10]))[:5]

                columns.append({
                    "name": h,
                    "type": col_type,
                    "non_null_count": len(non_null),
                    "null_count": null_count,
                    "null_pct": round(null_count / len(vals) * 100, 1) if vals else 0,
                    "sample_values": samples,
                })

            return json.dumps({
                "status": "ok",
                "file": path,
                "delimiter": delim,
                "encoding": encoding,
                "row_count": row_count,
                "column_count": len(headers),
                "columns": columns,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    print("[mcp-spreadsheet-pdf] CSV 工具已注册", flush=True)
