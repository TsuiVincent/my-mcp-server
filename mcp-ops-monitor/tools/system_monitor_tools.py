"""
系统资源监控工具
实现CPU、内存、磁盘、网络等服务器资源实时监控与告警。

工具列表：
- monitor_cpu: CPU使用率监控
- monitor_memory: 内存使用监控
- monitor_disk: 磁盘使用监控
- monitor_network: 网络IO监控
- monitor_processes: 进程列表监控
- monitor_system_info: 系统信息汇总
"""

import os
import sys
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_psutil_available = False
try:
    import psutil
    _psutil_available = True
except ImportError:
    pass


def _check_psutil():
    if not _psutil_available:
        return "【错误】psutil 库未安装。请执行: pip install psutil"
    return None


def _format_bytes(bytes_val: int) -> str:
    """格式化字节"""
    if bytes_val >= 1024 ** 4:
        return f"{bytes_val / (1024**4):.2f} TB"
    elif bytes_val >= 1024 ** 3:
        return f"{bytes_val / (1024**3):.2f} GB"
    elif bytes_val >= 1024 ** 2:
        return f"{bytes_val / (1024**2):.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f} KB"
    else:
        return f"{bytes_val} B"


def _monitor_cpu(interval: float = 1.0) -> str:
    """CPU使用率监控"""
    err = _check_psutil()
    if err:
        return err

    try:
        cpu_percent = psutil.cpu_percent(interval=min(interval, 1.0))
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        load_avg = psutil.getloadavg() if hasattr(psutil, "getloadavg") else None

        per_cpu = psutil.cpu_percent(interval=0, percpu=True)

        lines = [f"【CPU监控】{datetime.now().strftime('%H:%M:%S')}"]
        lines.append(f"  总使用率: {cpu_percent}%")
        lines.append(f"  核心数: {cpu_count} (物理: {psutil.cpu_count(logical=False)})")
        if cpu_freq:
            lines.append(f"  频率: {cpu_freq.current:.0f} MHz (最小: {cpu_freq.min:.0f}, 最大: {cpu_freq.max:.0f})")
        if load_avg:
            lines.append(f"  负载: 1min={load_avg[0]:.2f}, 5min={load_avg[1]:.2f}, 15min={load_avg[2]:.2f}")
        lines.append(f"  各核心: {', '.join(f'{p}%' for p in per_cpu)}")

        # 告警
        if cpu_percent > 90:
            lines.append("\n  【告警】CPU使用率超过90%！")
        elif cpu_percent > 70:
            lines.append("\n  【警告】CPU使用率超过70%")

        return "\n".join(lines)
    except Exception as e:
        return f"【CPU监控失败】{str(e)}"


def _monitor_memory() -> str:
    """内存使用监控"""
    err = _check_psutil()
    if err:
        return err

    try:
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        lines = [f"【内存监控】{datetime.now().strftime('%H:%M:%S')}"]
        lines.append(f"  物理内存:")
        lines.append(f"    总计: {_format_bytes(mem.total)}")
        lines.append(f"    已用: {_format_bytes(mem.used)} ({mem.percent}%)")
        lines.append(f"    可用: {_format_bytes(mem.available)}")
        lines.append(f"    空闲: {_format_bytes(mem.free)}")
        lines.append(f"  交换分区:")
        lines.append(f"    总计: {_format_bytes(swap.total)}")
        lines.append(f"    已用: {_format_bytes(swap.used)} ({swap.percent}%)")

        if mem.percent > 90:
            lines.append("\n  【告警】内存使用率超过90%！")
        elif mem.percent > 70:
            lines.append("\n  【警告】内存使用率超过70%")

        return "\n".join(lines)
    except Exception as e:
        return f"【内存监控失败】{str(e)}"


def _monitor_disk(path: str = "/") -> str:
    """磁盘使用监控"""
    err = _check_psutil()
    if err:
        return err

    try:
        if not os.path.exists(path):
            path = "C:\\" if sys.platform == "win32" else "/"

        lines = [f"【磁盘监控】{datetime.now().strftime('%H:%M:%S')}"]

        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                lines.append(f"\n  {partition.device} ({partition.mountpoint}) [{partition.fstype}]:")
                lines.append(f"    总计: {_format_bytes(usage.total)}")
                lines.append(f"    已用: {_format_bytes(usage.used)} ({usage.percent}%)")
                lines.append(f"    可用: {_format_bytes(usage.free)}")

                if usage.percent > 90:
                    lines.append(f"    【告警】磁盘使用率超过90%！")
            except PermissionError:
                continue

        return "\n".join(lines)
    except Exception as e:
        return f"【磁盘监控失败】{str(e)}"


def _monitor_network() -> str:
    """网络IO监控"""
    err = _check_psutil()
    if err:
        return err

    try:
        net_io = psutil.net_io_counters()
        net_connections = psutil.net_connections(kind="tcp")
        net_if = psutil.net_if_addrs()

        lines = [f"【网络监控】{datetime.now().strftime('%H:%M:%S')}"]
        lines.append(f"  IO统计:")
        lines.append(f"    发送: {_format_bytes(net_io.bytes_sent)}")
        lines.append(f"    接收: {_format_bytes(net_io.bytes_recv)}")
        lines.append(f"    发送包: {net_io.packets_sent}")
        lines.append(f"    接收包: {net_io.packets_recv}")
        lines.append(f"  TCP连接数: {len(net_connections)}")
        lines.append(f"  TCP状态: ESTABLISHED={sum(1 for c in net_connections if c.status == 'ESTABLISHED')}, "
                        f"LISTEN={sum(1 for c in net_connections if c.status == 'LISTEN')}")

        # 网络接口信息
        lines.append(f"\n  网络接口:")
        for if_name, addrs in net_if.items():
            for addr in addrs:
                if addr.family.name == "AF_INET":
                    lines.append(f"    {if_name}: {addr.address}/{addr.netmask}")

        return "\n".join(lines)
    except Exception as e:
        return f"【网络监控失败】{str(e)}"


def _monitor_processes(top_n: int = 10, sort_by: str = "memory") -> str:
    """进程列表监控"""
    err = _check_psutil()
    if err:
        return err

    try:
        sort_key = "memory_percent" if sort_by == "memory" else "cpu_percent"

        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent",
                                          "memory_percent", "memory_info"]):
            try:
                info = proc.info
                processes.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        processes.sort(key=lambda x: x.get(sort_key, 0) or 0, reverse=True)

        lines = [f"【进程监控 Top {top_n} (按{'内存' if sort_by == 'memory' else 'CPU'})】"]
        lines.append(f"{'PID':>6} {'进程名':<25} {'CPU%':>6} {'内存%':>6} {'内存':>10}")
        lines.append("-" * 60)

        for proc in processes[:top_n]:
            pid = proc.get("pid", 0)
            name = (proc.get("name") or "")[:25]
            cpu = proc.get("cpu_percent") or 0
            mem_pct = proc.get("memory_percent") or 0
            mem_info = proc.get("memory_info")
            mem_str = _format_bytes(mem_info.rss) if mem_info else "N/A"

            lines.append(f"{pid:>6} {name:<25} {cpu:>6.1f} {mem_pct:>6.1f} {mem_str:>10}")

        return "\n".join(lines)
    except Exception as e:
        return f"【进程监控失败】{str(e)}"


def _system_info() -> str:
    """系统信息汇总"""
    err = _check_psutil()
    if err:
        return err

    try:
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time

        lines = [f"【系统信息汇总】"]
        lines.append(f"  主机名: {os.uname().nodename if hasattr(os, 'uname') else 'N/A'}")
        lines.append(f"  系统: {sys.platform}")
        lines.append(f"  Python: {sys.version}")
        lines.append(f"  启动时间: {boot_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  运行时长: {str(uptime).split('.')[0]}")

        cpu = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/" if sys.platform != "win32" else "C:\\")

        lines.append(f"\n  资源使用:")
        lines.append(f"    CPU: {cpu}%")
        lines.append(f"    内存: {mem.percent}% ({_format_bytes(mem.used)}/{_format_bytes(mem.total)})")
        lines.append(f"    磁盘: {disk.percent}% ({_format_bytes(disk.used)}/{_format_bytes(disk.total)})")

        return "\n".join(lines)
    except Exception as e:
        return f"【系统信息获取失败】{str(e)}"


# ===================== 注册函数 =====================

def register_monitor_tools(mcp):
    """注册系统监控工具到 MCP 服务器"""

    @mcp.tool(
        name="monitor_cpu",
        description="监控CPU使用率、频率、负载等。Args: interval(采样间隔秒数,默认1.0)"
    )
    def monitor_cpu(interval: float = 1.0) -> str:
        return _monitor_cpu(interval)

    @mcp.tool(
        name="monitor_memory",
        description="监控物理内存和交换分区使用情况"
    )
    def monitor_memory() -> str:
        return _monitor_memory()

    @mcp.tool(
        name="monitor_disk",
        description="监控所有磁盘分区使用情况。Args: path(指定路径,可选)"
    )
    def monitor_disk(path: str = "") -> str:
        return _monitor_disk(path if path else ("C:\\" if sys.platform == "win32" else "/"))

    @mcp.tool(
        name="monitor_network",
        description="监控网络IO统计和连接状态"
    )
    def monitor_network() -> str:
        return _monitor_network()

    @mcp.tool(
        name="monitor_processes",
        description="查看Top N进程(按内存或CPU排序)。Args: top_n(显示数量,默认10), sort_by(排序方式:memory/cpu,默认memory)"
    )
    def monitor_processes(top_n: int = 10, sort_by: str = "memory") -> str:
        return _monitor_processes(top_n, sort_by)

    @mcp.tool(
        name="monitor_system_info",
        description="查看系统信息汇总(主机名、运行时长、资源使用等)"
    )
    def monitor_system_info() -> str:
        return _system_info()

    logger.info("系统监控工具已注册")
