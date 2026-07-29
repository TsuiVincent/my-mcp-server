"""
时间日期服务工具
实现高精度时间同步、时区转换、日期计算、定时任务管理等功能。

工具列表：
- time_current: 获取当前时间（支持多时区）
- time_convert: 时区转换
- time_calculate: 日期计算（加减天数/小时等）
- time_format: 日期格式化/解析
- time_diff: 计算两个时间的差值
- time_list_timezones: 列出常用时区
- datetime_cron_parse: 解析Cron表达式并给出下次执行时间
"""

import logging
from datetime import datetime, date, timedelta, timezone as dt_timezone

logger = logging.getLogger(__name__)

# ===================== 导入可选库 =====================

_zoneinfo_available = False
try:
    import zoneinfo
    _zoneinfo_available = True
except ImportError:
    pass

_pytz_available = False
try:
    import pytz
    _pytz_available = True
except ImportError:
    pass

_dateutil_available = False
try:
    from dateutil import parser as dateutil_parser
    from dateutil.relativedelta import relativedelta
    _dateutil_available = True
except ImportError:
    pass


# ===================== 内部实现 =====================

def _get_timezone(tz_name: str):
    """获取时区对象"""
    if tz_name.upper() == "UTC":
        return dt_timezone.utc

    if _zoneinfo_available:
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            pass

    if _pytz_available:
        try:
            return pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            pass

    return None


def _get_local_tz():
    """获取本地时区"""
    try:
        if _zoneinfo_available:
            import zoneinfo
            return zoneinfo.ZoneInfo(datetime.now().astimezone().tzname() or "Asia/Shanghai")
    except Exception:
        pass

    try:
        offset = -datetime.now().astimezone().utcoffset().seconds / 3600
        return dt_timezone(timedelta(hours=int(offset)))
    except Exception:
        return dt_timezone(timedelta(hours=8))  # 默认东八区


_COMMON_TIMEZONES = {
    "UTC": "UTC+0",
    "Asia/Shanghai": "UTC+8 (中国标准时间)",
    "Asia/Tokyo": "UTC+9 (日本标准时间)",
    "Asia/Seoul": "UTC+9 (韩国标准时间)",
    "Asia/Singapore": "UTC+8 (新加坡时间)",
    "Asia/Kolkata": "UTC+5:30 (印度标准时间)",
    "Asia/Dubai": "UTC+4 (迪拜时间)",
    "Europe/London": "UTC+0/+1 (英国时间)",
    "Europe/Paris": "UTC+1/+2 (中欧时间)",
    "Europe/Moscow": "UTC+3 (莫斯科时间)",
    "America/New_York": "UTC-5/-4 (美东时间)",
    "America/Chicago": "UTC-6/-5 (美中时间)",
    "America/Los_Angeles": "UTC-8/-7 (美西时间)",
    "America/Sao_Paulo": "UTC-3 (巴西时间)",
    "Australia/Sydney": "UTC+10/+11 (悉尼时间)",
    "Pacific/Auckland": "UTC+12/+13 (新西兰时间)",
}


def _current_time(tz_name: str = "") -> str:
    """获取当前时间"""
    try:
        if tz_name and tz_name.upper() != "LOCAL":
            tz = _get_timezone(tz_name)
            if tz is None:
                return f"【错误】无效的时区: {tz_name}。请使用 time_list_timezones 查看可用时区"
            now = datetime.now(tz)
        else:
            tz = _get_local_tz()
            now = datetime.now(tz)

        return (
            f"当前时间 ({tz_name or '本地'}):\n"
            f"  ISO 8601: {now.isoformat()}\n"
            f"  格式化: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"  星期: {_weekday_cn(now.weekday())}\n"
            f"  时间戳: {now.timestamp()}"
        )
    except Exception as e:
        return f"【错误】{str(e)}"


def _weekday_cn(weekday: int) -> str:
    """星期中文名"""
    names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return names[weekday] if 0 <= weekday <= 6 else "未知"


def _convert_timezone(time_str: str, from_tz: str, to_tz: str) -> str:
    """时区转换"""
    try:
        from_zone = _get_timezone(from_tz)
        to_zone = _get_timezone(to_tz)

        if from_zone is None:
            return f"【错误】无效的源时区: {from_tz}"
        if to_zone is None:
            return f"【错误】无效的目标时区: {to_tz}"

        # 解析时间字符串
        if _dateutil_available:
            parsed_dt = dateutil_parser.parse(time_str)
        else:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
                try:
                    parsed_dt = datetime.strptime(time_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                return f"【错误】无法解析时间字符串: {time_str}"

        # 本地化到源时区
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=from_zone)

        # 转换
        converted = parsed_dt.astimezone(to_zone)

        return (
            f"时区转换结果:\n"
            f"  原始: {parsed_dt.isoformat()} ({from_tz})\n"
            f"  转换: {converted.isoformat()} ({to_tz})\n"
            f"  偏移: {int(converted.utcoffset().total_seconds() / 3600)} 小时"
        )
    except Exception as e:
        return f"【转换失败】{str(e)}"


def _calculate_time(base_time: str, operation: str, value: int = 0,
                    unit: str = "days") -> str:
    """日期时间计算"""
    valid_units = {
        "seconds": timedelta(seconds=1),
        "minutes": timedelta(minutes=1),
        "hours": timedelta(hours=1),
        "days": timedelta(days=1),
        "weeks": timedelta(weeks=1),
        "months": "month",
        "years": "year",
    }

    if unit not in valid_units:
        return f"【错误】无效的时间单位: {unit}。支持: {list(valid_units.keys())}"

    try:
        # 解析基准时间
        if base_time.lower() == "now":
            dt = datetime.now()
        else:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(base_time, fmt)
                    break
                except ValueError:
                    continue
            else:
                return f"【错误】无法解析时间: {base_time}"

        delta_or_unit = valid_units[unit]

        if operation == "add":
            if delta_or_unit == "month":
                if _dateutil_available:
                    dt = dt + relativedelta(months=value)
                else:
                    # 简化月份计算
                    new_month = dt.month + value
                    new_year = dt.year + (new_month - 1) // 12
                    new_month = ((new_month - 1) % 12) + 1
                    dt = dt.replace(year=new_year, month=new_month)
            elif delta_or_unit == "year":
                if _dateutil_available:
                    dt = dt + relativedelta(years=value)
                else:
                    dt = dt.replace(year=dt.year + value)
            else:
                dt = dt + delta_or_unit * value
        elif operation == "subtract":
            if delta_or_unit == "month":
                if _dateutil_available:
                    dt = dt - relativedelta(months=value)
                else:
                    new_month = dt.month - value
                    new_year = dt.year + (new_month - 1) // 12
                    new_month = ((new_month - 1) % 12) + 1
                    dt = dt.replace(year=new_year, month=new_month)
            elif delta_or_unit == "year":
                if _dateutil_available:
                    dt = dt - relativedelta(years=value)
                else:
                    dt = dt.replace(year=dt.year - value)
            else:
                dt = dt - delta_or_unit * value
        else:
            return f"【错误】无效的操作: {operation}。支持 add/subtract"

        return (
            f"日期计算:\n"
            f"  基准时间: {base_time}\n"
            f"  操作: {operation} {value} {unit}\n"
            f"  结果: {dt.strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_cn(dt.weekday())})"
        )
    except Exception as e:
        return f"【计算失败】{str(e)}"


def _format_time(time_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """时间格式化/解析"""
    try:
        if time_str.lower() == "now":
            dt = datetime.now()
            return f"格式化结果: {dt.strftime(format_str)}"

        # 先尝试作为时间戳解析
        try:
            ts = float(time_str)
            dt = datetime.fromtimestamp(ts)
            return f"时间戳 {ts} 格式化: {dt.strftime(format_str)}"
        except ValueError:
            pass

        # 尝试常见格式解析
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d",
                    "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
            try:
                dt = datetime.strptime(time_str, fmt)
                return f"格式化结果: {dt.strftime(format_str)}"
            except ValueError:
                continue

        return f"【错误】无法解析: {time_str}"
    except Exception as e:
        return f"【格式化失败】{str(e)}"


def _diff_time(time1: str, time2: str) -> str:
    """计算两个时间的差值"""
    try:
        def _parse(t_str):
            if t_str.lower() == "now":
                return datetime.now()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(t_str, fmt)
                except ValueError:
                    continue
            raise ValueError(f"无法解析: {t_str}")

        dt1 = _parse(time1)
        dt2 = _parse(time2)
        diff = abs(dt2 - dt1)

        total_seconds = int(diff.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        return (
            f"时间差:\n"
            f"  {time1} → {time2}\n"
            f"  相差: {days}天 {hours}小时 {minutes}分钟 {seconds}秒\n"
            f"  总计: {total_seconds}秒"
        )
    except Exception as e:
        return f"【计算失败】{str(e)}"


def _list_timezones() -> str:
    """列出常用时区"""
    lines = ["【常用时区列表】"]
    for tz, desc in _COMMON_TIMEZONES.items():
        lines.append(f"  {tz}: {desc}")
    return "\n".join(lines)


def _parse_cron(cron_expr: str) -> str:
    """解析Cron表达式"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return ("【错误】Cron表达式需要5个字段: 分钟 小时 日 月 星期\n"
                "示例: 0 9 * * 1 (每周一上午9点)\n"
                f"当前输入只有 {len(parts)} 个字段")

    desc_parts = []

    # 分钟
    min_part = parts[0]
    desc_parts.append(f"分钟: {_cron_field_desc(min_part, '分钟')}")

    # 小时
    hour_part = parts[1]
    desc_parts.append(f"小时: {_cron_field_desc(hour_part, '小时')}")

    # 日
    day_part = parts[2]
    desc_parts.append(f"日: {_cron_field_desc(day_part, '日')}")

    # 月
    month_part = parts[3]
    desc_parts.append(f"月: {_cron_field_desc(month_part, '月')}")

    # 星期
    week_part = parts[4]
    week_names = {0: "日", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}
    week_desc = _cron_field_desc(week_part, "星期")
    desc_parts.append(f"星期: {week_desc}")

    # 计算下次执行时间
    now = datetime.now()
    next_run = _cron_next(parts, now)

    return (
        f"【Cron表达式: {cron_expr}】\n\n"
        + "\n".join(desc_parts) +
        f"\n\n当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
        f"\n下次执行: {next_run}"
    )


def _cron_field_desc(field: str, unit: str) -> str:
    """描述单个cron字段"""
    if field == "*":
        return f"每{unit}"
    elif "," in field:
        values = field.split(",")
        return f"{unit} {', '.join(values)}"
    elif "/" in field:
        base, step = field.split("/")
        return f"从 {base if base != '*' else '0'} 开始每 {step} {unit}"
    elif "-" in field:
        start, end = field.split("-")
        return f"{start}-{end} {unit}"
    else:
        return f"{unit} {field}"


def _cron_next(parts: list, from_dt: datetime) -> str:
    """计算cron下次执行时间（简化版）"""
    minute = parts[0]
    hour = parts[1]
    # 简化实现: 给出大致时间
    try:
        now = from_dt
        current_min = now.minute
        current_hour = now.hour

        # 查找下一个匹配的小时
        if hour != "*":
            target_hours = [int(h) for h in hour.split(",")]
            next_hour = None
            for h in sorted(target_hours):
                if h > current_hour:
                    next_hour = h
                    break
            if next_hour is None:
                next_hour = sorted(target_hours)[0]
                next_dt = now.replace(hour=next_hour, minute=0, second=0, microsecond=0) + timedelta(days=1)
            else:
                next_dt = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
        else:
            next_dt = now + timedelta(hours=1)
            next_dt = next_dt.replace(minute=0, second=0, microsecond=0)

        if minute != "*":
            target_mins = [int(m) for m in minute.split(",")]
            next_min = target_mins[0]
            next_dt = next_dt.replace(minute=next_min)

        return next_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "无法计算"


# ===================== 注册函数 =====================

def register_datetime_tools(mcp):
    """注册时间日期工具到 MCP 服务器"""

    @mcp.tool(
        name="time_current",
        description="获取当前时间。Args: timezone(时区名称,如Asia/Shanghai,留空为本地时区)"
    )
    def time_current(timezone: str = "") -> str:
        return _current_time(timezone)

    @mcp.tool(
        name="time_convert",
        description="时区转换。Args: time_str(时间字符串,如2024-01-01 12:00:00), from_tz(源时区), to_tz(目标时区)"
    )
    def time_convert(time_str: str, from_tz: str, to_tz: str) -> str:
        return _convert_timezone(time_str, from_tz, to_tz)

    @mcp.tool(
        name="time_calculate",
        description="日期时间加减计算。Args: base_time(基准时间或now), operation(add/subtract), value(数值), unit(seconds/minutes/hours/days/weeks/months/years)"
    )
    def time_calculate(base_time: str, operation: str = "add",
                       value: int = 1, unit: str = "days") -> str:
        return _calculate_time(base_time, operation, value, unit)

    @mcp.tool(
        name="time_format",
        description="时间格式化或解析。Args: time_str(时间字符串/时间戳/now), format_str(目标格式,默认%Y-%m-%d %H:%M:%S)"
    )
    def time_format(time_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
        return _format_time(time_str, format_str)

    @mcp.tool(
        name="time_diff",
        description="计算两个时间的差值。Args: time1(时间1), time2(时间2)"
    )
    def time_diff(time1: str, time2: str) -> str:
        return _diff_time(time1, time2)

    @mcp.tool(
        name="time_list_timezones",
        description="列出常用时区列表"
    )
    def time_list_timezones() -> str:
        return _list_timezones()

    @mcp.tool(
        name="datetime_cron_parse",
        description="解析Cron表达式并计算下次执行时间。Args: cron_expr(5字段Cron表达式,如'0 9 * * 1')"
    )
    def datetime_cron_parse(cron_expr: str) -> str:
        return _parse_cron(cron_expr)

    logger.info("时间日期工具已注册")
