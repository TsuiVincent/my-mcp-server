"""
日志分析工具
支持内网应用日志的收集、解析与异常检测。

工具列表：
- log_parse_file: 解析单个日志文件
- log_search_errors: 搜索日志中的错误/异常
- log_summary: 生成日志摘要统计
- log_tail: 查看日志尾部内容
- log_filter: 按关键字/时间范围过滤日志
"""

import os
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter, defaultdict

logger = logging.getLogger(__name__)

# ===================== 日志级别定义 =====================

_LOG_LEVELS = {
    "CRITICAL": 50, "FATAL": 50,
    "ERROR": 40, "ERR": 40,
    "WARNING": 30, "WARN": 30,
    "INFO": 20,
    "DEBUG": 10, "TRACE": 10,
}

# 常见日志时间格式
_TIME_PATTERNS = [
    (r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[.,]\d{3}', '%Y-%m-%d %H:%M:%S.%f'),
    (r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', '%Y-%m-%d %H:%M:%S'),
    (r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}', '%Y/%m/%d %H:%M:%S'),
    (r'\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}', '%d/%b/%Y:%H:%M:%S'),
]

# 错误异常模式
_ERROR_PATTERNS = [
    (r'ERROR|CRITICAL|FATAL|Fatal|Exception|Traceback|traceback', 'error'),
    (r'WARNING|WARN|Warning', 'warning'),
    (r'PANIC|panic|segmentation fault|out of memory|OOM', 'critical'),
]


# ===================== 内部实现 =====================

def _detect_log_format(lines: list) -> dict:
    """检测日志格式"""
    sample = "\n".join(lines[:50])

    info = {
        "has_timestamps": False,
        "has_levels": False,
        "time_pattern": None,
        "time_format": None,
    }

    for pattern, fmt in _TIME_PATTERNS:
        if re.search(pattern, sample):
            info["has_timestamps"] = True
            info["time_pattern"] = pattern
            info["time_format"] = fmt
            break

    for keyword, _ in _ERROR_PATTERNS:
        if re.search(keyword, sample):
            info["has_levels"] = True
            break

    return info


def _parse_time_from_line(line: str, pattern: str, fmt: str) -> datetime:
    """从行中提取时间"""
    match = re.search(pattern, line)
    if match:
        try:
            time_str = match.group()
            # 处理毫秒
            if ',' in time_str:
                time_str = time_str.replace(',', '.')
                if '.' in fmt:
                    pass
            return datetime.strptime(time_str, fmt)
        except ValueError:
            pass
    return None


def _read_log_file(file_path: str, max_lines: int = 10000) -> list:
    """读取日志文件"""
    if not os.path.exists(file_path):
        return None

    lines = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                lines.append(line.rstrip('\n\r'))
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="gbk") as f:
                for i, line in enumerate(f):
                    if i >= max_lines:
                        break
                    lines.append(line.rstrip('\n\r'))
        except Exception:
            return None

    return lines


def _parse_log_file(file_path: str, max_lines: int = 5000) -> str:
    """解析日志文件"""
    lines = _read_log_file(file_path, max_lines)
    if lines is None:
        return f"【错误】无法读取文件: {file_path}"

    if not lines:
        return f"【提示】文件为空: {file_path}"

    format_info = _detect_log_format(lines)

    # 统计各级别日志
    level_counts = Counter()
    for line in lines:
        for pattern, level_name in _ERROR_PATTERNS:
            if re.search(pattern, line):
                level_counts[level_name] += 1
                break
        else:
            level_counts["info"] += 1

    # 时间范围
    time_range = "未知"
    if format_info["has_timestamps"]:
        first_time = _parse_time_from_line(lines[0], format_info["time_pattern"],
                                            format_info["time_format"])
        last_time = _parse_time_from_line(lines[-1], format_info["time_pattern"],
                                           format_info["time_format"])
        if first_time and last_time:
            time_range = f"{first_time.strftime('%Y-%m-%d %H:%M:%S')} ~ {last_time.strftime('%Y-%m-%d %H:%M:%S')}"

    file_stat = os.stat(file_path)
    file_size = file_stat.st_size

    result = [
        f"【日志解析: {os.path.basename(file_path)}】",
        f"  文件大小: {_format_size(file_size)}",
        f"  总行数: {len(lines)} (已读取前{max_lines}行)" if len(lines) >= max_lines else f"  总行数: {len(lines)}",
        f"  时间范围: {time_range}",
        f"  日志级别分布:",
    ]
    for level in ["critical", "error", "warning", "info"]:
        count = level_counts.get(level, 0)
        bar = "█" * min(count // (max(level_counts.values() or [1]) // 20 + 1) + 1, 50)
        result.append(f"    {level}: {count:>6} {bar}")

    return "\n".join(result)


def _search_errors(file_path: str, max_results: int = 20) -> str:
    """搜索日志中的错误和异常"""
    lines = _read_log_file(file_path)
    if lines is None:
        return f"【错误】无法读取文件: {file_path}"

    errors_found = []
    in_traceback = False
    current_traceback = []

    for i, line in enumerate(lines):
        is_traceback_line = line.startswith(("  File ", "    ", "Traceback"))
        has_error = re.search(r'(ERROR|CRITICAL|FATAL|Exception|Error:|panic)', line)

        if is_traceback_line:
            if not in_traceback:
                in_traceback = True
                current_traceback = []
            current_traceback.append((i + 1, line))
        elif in_traceback:
            # traceback结束
            errors_found.append({
                "line_no": current_traceback[0][0],
                "type": "traceback",
                "content": "\n".join(l for _, l in current_traceback[:10])
            })
            in_traceback = False
            current_traceback = []

        if has_error and not is_traceback_line:
            errors_found.append({
                "line_no": i + 1,
                "type": "error",
                "content": line
            })

    if in_traceback and current_traceback:
        errors_found.append({
            "line_no": current_traceback[0][0],
            "type": "traceback",
            "content": "\n".join(l for _, l in current_traceback[:10])
        })

    if not errors_found:
        return f"【日志错误搜索】\n文件: {os.path.basename(file_path)}\n未发现错误或异常。"

    total = len(errors_found)
    show = errors_found[:max_results]

    result = [f"【日志错误搜索】\n文件: {os.path.basename(file_path)}"]
    result.append(f"共发现 {total} 处错误/异常，显示前 {len(show)} 处:\n")

    for i, err in enumerate(show, 1):
        result.append(f"{i}. [行{err['line_no']}] [{err['type']}]")
        result.append(f"   {err['content'][:300]}")
        result.append("")

    return "\n".join(result)


def _log_summary(file_path: str, group_by: str = "hour") -> str:
    """日志摘要统计"""
    lines = _read_log_file(file_path)
    if lines is None:
        return f"【错误】无法读取文件: {file_path}"

    format_info = _detect_log_format(lines)

    # 按时间分组统计
    time_groups = defaultdict(int)
    error_groups = defaultdict(int)
    total_with_time = 0

    for line in lines:
        if format_info["has_timestamps"]:
            dt = _parse_time_from_line(line, format_info["time_pattern"],
                                        format_info["time_format"])
            if dt:
                total_with_time += 1
                if group_by == "hour":
                    key = dt.strftime("%Y-%m-%d %H:00")
                elif group_by == "day":
                    key = dt.strftime("%Y-%m-%d")
                elif group_by == "minute":
                    key = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    key = dt.strftime("%Y-%m-%d %H:00")

                time_groups[key] += 1

                if re.search(r'(ERROR|CRITICAL|FATAL|Exception)', line):
                    error_groups[key] += 1

    result = [f"【日志摘要: {os.path.basename(file_path)}】"]
    result.append(f"总行数: {len(lines)}")
    result.append(f"有时间戳行: {total_with_time}")

    if time_groups:
        result.append(f"\n按{group_by}分组的日志量:")
        result.append(f"{'时间':<20} {'总数':>6} {'错误':>6} {'占比'}")
        result.append("-" * 45)

        sorted_groups = sorted(time_groups.items())
        for time_key, count in sorted_groups[-24:]:  # 最近24个时间段
            errors = error_groups.get(time_key, 0)
            bar_len = min(count // (max(time_groups.values() or [1]) // 20 + 1) + 1, 30)
            bar = "█" * bar_len
            result.append(f"{time_key:<20} {count:>6} {errors:>6} {bar}")

    return "\n".join(result)


def _tail_log(file_path: str, lines_count: int = 100) -> str:
    """查看日志尾部"""
    if not os.path.exists(file_path):
        return f"【错误】文件不存在: {file_path}"

    try:
        lines = _read_log_file(file_path, 0)  # 读取全部
        if lines is None:
            return f"【错误】无法读取文件: {file_path}"

        tail_lines = lines[-lines_count:] if len(lines) > lines_count else lines

        result = [
            f"【日志尾部: {os.path.basename(file_path)}】",
            f"共 {len(lines)} 行，显示最后 {len(tail_lines)} 行:\n"
        ]
        for line in tail_lines:
            result.append(line)

        return "\n".join(result)
    except Exception as e:
        return f"【错误】{str(e)}"


def _filter_logs(file_path: str, keyword: str = "",
                  level: str = "", start_time: str = "",
                  end_time: str = "", max_results: int = 100) -> str:
    """按条件过滤日志"""
    lines = _read_log_file(file_path, 20000)
    if lines is None:
        return f"【错误】无法读取文件: {file_path}"

    format_info = _detect_log_format(lines)
    filtered = []

    # 解析时间范围
    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    if end_time:
        try:
            end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    for line in lines:
        # 关键字过滤
        if keyword and keyword.lower() not in line.lower():
            continue

        # 级别过滤
        if level:
            level_upper = level.upper()
            level_matched = False
            for pattern, lvl_name in _ERROR_PATTERNS:
                if lvl_name.upper() == level_upper and re.search(pattern, line):
                    level_matched = True
                    break
            if not level_matched and level_upper != "INFO":
                if level_upper == "INFO" and re.search(r'(ERROR|WARN|CRITICAL|FATAL|Exception)', line):
                    continue
                elif level_upper != "INFO":
                    continue

        # 时间过滤
        if start_dt or end_dt:
            dt = _parse_time_from_line(line, format_info["time_pattern"],
                                        format_info["time_format"]) \
                if format_info["has_timestamps"] else None
            if dt:
                if start_dt and dt < start_dt:
                    continue
                if end_dt and dt > end_dt:
                    continue

        filtered.append(line)
        if len(filtered) >= max_results:
            break

    if not filtered:
        return f"【过滤结果】未找到匹配的日志行"

    result = [
        f"【日志过滤: {os.path.basename(file_path)}】",
        f"条件: keyword='{keyword}', level='{level}', "
        f"time='{start_time}~{end_time}'",
        f"匹配: {len(filtered)} 行 (最多显示{max_results}行)\n"
    ]

    for line in filtered:
        result.append(line)

    return "\n".join(result)


def _format_size(size: int) -> str:
    """格式化文件大小"""
    if size >= 1024 ** 3:
        return f"{size / (1024**3):.2f} GB"
    elif size >= 1024 ** 2:
        return f"{size / (1024**2):.2f} MB"
    elif size >= 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size} B"


# ===================== 注册函数 =====================

def register_log_analyzer_tools(mcp):
    """注册日志分析工具到 MCP 服务器"""

    @mcp.tool(
        name="log_parse_file",
        description="解析日志文件，分析日志级别分布、时间范围。Args: file_path(日志文件路径,必填), max_lines(最大读取行数,默认5000)"
    )
    def log_parse_file(file_path: str, max_lines: int = 5000) -> str:
        return _parse_log_file(file_path, max_lines)

    @mcp.tool(
        name="log_search_errors",
        description="搜索日志中的错误和异常（ERROR/CRITICAL/Exception/Traceback）。Args: file_path(日志文件路径,必填), max_results(最大结果数,默认20)"
    )
    def log_search_errors(file_path: str, max_results: int = 20) -> str:
        return _search_errors(file_path, max_results)

    @mcp.tool(
        name="log_summary",
        description="生成日志摘要统计（按时间分组统计日志量趋势）。Args: file_path(日志文件路径,必填), group_by(分组方式:hour/day/minute,默认hour)"
    )
    def log_summary(file_path: str, group_by: str = "hour") -> str:
        return _log_summary(file_path, group_by)

    @mcp.tool(
        name="log_tail",
        description="查看日志文件尾部内容。Args: file_path(日志文件路径,必填), lines_count(行数,默认100)"
    )
    def log_tail(file_path: str, lines_count: int = 100) -> str:
        return _tail_log(file_path, lines_count)

    @mcp.tool(
        name="log_filter",
        description="按关键字/日志级别/时间范围过滤日志。Args: file_path(日志文件路径,必填), keyword(关键字,可选), level(日志级别:error/warning/info,可选), start_time(开始时间YYYY-MM-DD HH:MM:SS,可选), end_time(结束时间,可选), max_results(最大结果数,默认100)"
    )
    def log_filter(file_path: str, keyword: str = "", level: str = "",
                   start_time: str = "", end_time: str = "",
                   max_results: int = 100) -> str:
        return _filter_logs(file_path, keyword, level, start_time, end_time, max_results)

    logger.info("日志分析工具已注册")
