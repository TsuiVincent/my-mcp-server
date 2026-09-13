"""
数据可视化与报表工具
支持多种图表类型（折线图、柱状图、饼图、散点图、热力图、箱线图、漏斗图），
实现数据导入、图表生成及报表导出功能，支持自定义模板。
图表默认以SVG矢量格式返回，可直接嵌入HTML预览，缩放无损；
也可通过 format="png" 输出PNG位图（返回 base64，便于平台托管为下载链接）。

本次升级要点：
- 新增 format 参数（svg/png，默认 svg，向后兼容）；
- 注入中文字体配置，避免中文标题/标签乱码；
- 补齐 viz_heatmap / viz_boxplot / viz_funnel 三个图表；
- 修正 viz_create_report 主题未透传问题；
- viz_svg_to_file 输出限定在会话工作目录内。

工具列表：
- viz_line_chart: 生成折线图
- viz_bar_chart: 生成柱状图
- viz_pie_chart: 生成饼图
- viz_scatter_chart: 生成散点图
- viz_heatmap: 生成热力图
- viz_boxplot: 生成箱线图
- viz_funnel: 生成漏斗图
- viz_create_report: 创建多图表报表
- viz_svg_to_file: 将SVG图表保存为文件（限会话工作目录）
"""

import os
import io
import json
import base64
import logging
import tempfile
import re

logger = logging.getLogger(__name__)

# 设置matplotlib非交互后端与缓存目录（未显式配置时使用临时目录，避免只读容器报错）
os.environ["MPLBACKEND"] = "Agg"
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mplconfig"))

# 中文字体候选（按优先级），命中系统已安装字体后注入 matplotlib
_CN_FONT_CANDIDATES = [
    "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", "Source Han Sans CN",
    "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
    "Microsoft YaHei", "SimHei", "PingFang SC", "Hiragino Sans GB", "Arial Unicode MS",
]


def _check_matplotlib():
    """检查并初始化matplotlib（含中文字体注入）"""
    try:
        import matplotlib
        matplotlib.use("Agg")  # 非交互后端
        from matplotlib import font_manager
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    try:
        available = {f.name for f in font_manager.fontManager.ttflist}
        picked = [name for name in _CN_FONT_CANDIDATES if name in available]
        matplotlib.rcParams["font.sans-serif"] = picked + ["DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False  # 负号正常显示
    except Exception as e:  # 字体探测失败不影响出图
        logger.warning("中文字体注入失败: %s", e)
    return plt


# ===================== 图表主题配置 =====================

_CHART_THEMES = {
    "default": {
        "bg_color": "#ffffff",
        "grid_color": "#e0e0e0",
        "text_color": "#333333",
        "colors": ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
                    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]
    },
    "dark": {
        "bg_color": "#2d2d2d",
        "grid_color": "#555555",
        "text_color": "#e0e0e0",
        "colors": ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f"]
    },
    "colorblind": {
        "bg_color": "#ffffff",
        "grid_color": "#cccccc",
        "text_color": "#000000",
        "colors": ["#117733", "#332288", "#88ccee", "#ddcc77", "#cc6677",
                    "#aa4499", "#44aa99", "#882255", "#6699cc", "#999933"]
    }
}


def _get_theme(theme_name: str = "default") -> dict:
    """获取图表主题"""
    return _CHART_THEMES.get(theme_name, _CHART_THEMES["default"])


# SVG包装标记，便于解析端提取原始SVG
SVG_START = "<!-- SVG_CHART_START -->"
SVG_END = "<!-- SVG_CHART_END -->"


def _parse_data(data_json: str) -> dict:
    """解析JSON数据"""
    try:
        data = json.loads(data_json)
        return {"success": True, "data": data}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON解析失败: {str(e)}"}


def _fig_to_svg(fig) -> str:
    """将matplotlib图形转为SVG字符串"""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", facecolor=fig.get_facecolor())
    svg_content = buf.getvalue()
    buf.close()
    return svg_content


def _fig_to_png(fig) -> bytes:
    """将matplotlib图形转为PNG字节"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150,
                facecolor=fig.get_facecolor())
    data = buf.getvalue()
    buf.close()
    return data


def _safe_filename(name: str, ext: str) -> str:
    """由标题生成安全文件名"""
    base = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", str(name or "chart")).strip(" ._")
    base = base[:60] or "chart"
    return f"{base}.{ext.lstrip('.')}"


def _render(fig, plt, title: str, fmt: str = "svg") -> str:
    """按格式输出图形：svg 返回内联SVG文本，png 返回含 base64 的 JSON。"""
    fmt = (fmt or "svg").strip().lower()
    try:
        if fmt == "png":
            data = _fig_to_png(fig)
            payload = {
                "message": f"【{title}】PNG 图表已生成",
                "format": "png",
                "filename": _safe_filename(title, "png"),
                "size_bytes": len(data),
                "base64_data": base64.b64encode(data).decode("ascii"),
                "usage": "解码 base64_data 保存为 .png；平台会自动托管为下载链接。",
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
        svg = _fig_to_svg(fig)
        return f"【{title}】\n{SVG_START}\n{svg}\n{SVG_END}"
    finally:
        try:
            plt.close(fig)
        except Exception:
            pass


def _parse_list(data_str: str):
    """解析逗号分隔的数字列表"""
    items = [x.strip() for x in data_str.split(",") if x.strip()]
    result = []
    for item in items:
        try:
            result.append(float(item))
        except ValueError:
            pass
    return result


def _resolve_output_path(file_path: str, workdir: str) -> str:
    """将会话工作目录外的路径收敛回工作目录，防止越权落盘。"""
    wd = os.path.abspath(workdir)
    target = file_path or "chart.svg"
    candidate = target if os.path.isabs(target) else os.path.join(wd, target)
    candidate = os.path.abspath(candidate)
    try:
        if os.path.commonpath([candidate, wd]) != wd:
            candidate = os.path.join(wd, os.path.basename(target))
    except ValueError:  # 不同盘符
        candidate = os.path.join(wd, os.path.basename(target))
    return candidate


# ===================== 图表生成 =====================

def _create_line_chart(data_json: str, title: str = "折线图",
                       xlabel: str = "X", ylabel: str = "Y",
                       theme: str = "default", fmt: str = "svg") -> str:
    """生成折线图"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。请执行: pip install matplotlib"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        data = parsed["data"]

        fig, ax = plt.subplots(figsize=(8, 4.5))
        fig.patch.set_facecolor(theme_config["bg_color"])
        ax.set_facecolor(theme_config["bg_color"])

        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                # 多系列数据：[{"label": "系列1", "values": [1,2,3]}, ...]
                for idx, series in enumerate(data):
                    color = theme_config["colors"][idx % len(theme_config["colors"])]
                    ax.plot(range(len(series.get("values", []))),
                            series.get("values", []),
                            label=series.get("label", f"系列{idx+1}"),
                            color=color, marker="o", markersize=4, linewidth=1.5)
                ax.legend()
            elif data and isinstance(data[0], (int, float)):
                ax.plot(range(len(data)), data, color=theme_config["colors"][0],
                        marker="o", markersize=4, linewidth=1.5)
            else:
                # [[x1,y1], [x2,y2], ...]
                xs = [p[0] for p in data]
                ys = [p[1] for p in data]
                ax.plot(xs, ys, color=theme_config["colors"][0],
                        marker="o", markersize=4, linewidth=1.5)

        ax.set_title(title, color=theme_config["text_color"], fontsize=14)
        ax.set_xlabel(xlabel, color=theme_config["text_color"])
        ax.set_ylabel(ylabel, color=theme_config["text_color"])
        ax.grid(True, color=theme_config["grid_color"], alpha=0.5)
        ax.tick_params(colors=theme_config["text_color"])

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_bar_chart(data_json: str, title: str = "柱状图",
                      xlabel: str = "类别", ylabel: str = "数值",
                      theme: str = "default", horizontal: bool = False,
                      fmt: str = "svg") -> str:
    """生成柱状图"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        data = parsed["data"]

        fig, ax = plt.subplots(figsize=(8, 4.5))
        fig.patch.set_facecolor(theme_config["bg_color"])
        ax.set_facecolor(theme_config["bg_color"])

        if isinstance(data, list) and data and isinstance(data[0], dict):
            # {"labels": [...], "values": [...]} 格式
            labels = data[0].get("labels", []) or [str(i) for i in range(len(data[0].get("values", [])))]
            values = data[0].get("values", [])
        elif isinstance(data, dict):
            labels = list(data.keys())
            values = list(data.values())
        else:
            return '【错误】数据格式不支持。请使用 [{"labels":[...], "values":[...]}] 或 {"key":value} 格式'

        colors = [theme_config["colors"][i % len(theme_config["colors"])] for i in range(len(values))]

        if horizontal:
            ax.barh(labels, values, color=colors)
            ax.set_xlabel(ylabel, color=theme_config["text_color"])
        else:
            ax.bar(labels, values, color=colors)
            ax.set_ylabel(ylabel, color=theme_config["text_color"])

        ax.set_title(title, color=theme_config["text_color"], fontsize=14)
        ax.set_xlabel(xlabel if not horizontal else ylabel, color=theme_config["text_color"])
        ax.grid(axis="y" if not horizontal else "x",
                color=theme_config["grid_color"], alpha=0.3)

        # 旋转标签防止重叠
        if not horizontal:
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_pie_chart(data_json: str, title: str = "饼图",
                      theme: str = "default",
                      show_percent: bool = True, fmt: str = "svg") -> str:
    """生成饼图"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        data = parsed["data"]

        if isinstance(data, dict):
            labels = list(data.keys())
            values = list(data.values())
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            labels = [d.get("label", f"项目{i}") for i, d in enumerate(data)]
            values = [d.get("value", 0) for d in data]
        else:
            return "【错误】数据格式不支持"

        fig, ax = plt.subplots(figsize=(6, 6))
        fig.patch.set_facecolor(theme_config["bg_color"])

        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels if not show_percent else None,
            autopct="%1.1f%%" if show_percent else None,
            colors=theme_config["colors"][:len(values)],
            startangle=90,
            pctdistance=0.75
        )

        if show_percent:
            for t in autotexts:
                t.set_fontsize(9)
                t.set_color(theme_config["text_color"])

        ax.set_title(title, color=theme_config["text_color"], fontsize=14)

        # 图例
        ax.legend(wedges, labels, title="图例", loc="center left",
                  bbox_to_anchor=(1, 0, 0.5, 1))

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_scatter_chart(data_json: str, title: str = "散点图",
                          xlabel: str = "X", ylabel: str = "Y",
                          theme: str = "default", fmt: str = "svg") -> str:
    """生成散点图"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        data = parsed["data"]

        fig, ax = plt.subplots(figsize=(7, 5))
        fig.patch.set_facecolor(theme_config["bg_color"])
        ax.set_facecolor(theme_config["bg_color"])

        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                for idx, series in enumerate(data):
                    color = theme_config["colors"][idx % len(theme_config["colors"])]
                    xs = series.get("x", [])
                    ys = series.get("y", [])
                    ax.scatter(xs, ys, label=series.get("label", f"系列{idx+1}"),
                              color=color, alpha=0.7, s=30)
                ax.legend()
            elif data and isinstance(data[0], list):
                xs = [p[0] for p in data]
                ys = [p[1] for p in data]
                ax.scatter(xs, ys, color=theme_config["colors"][0], alpha=0.7, s=30)

        ax.set_title(title, color=theme_config["text_color"], fontsize=14)
        ax.set_xlabel(xlabel, color=theme_config["text_color"])
        ax.set_ylabel(ylabel, color=theme_config["text_color"])
        ax.grid(True, color=theme_config["grid_color"], alpha=0.5)
        ax.tick_params(colors=theme_config["text_color"])

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _matrix_from_data(data) -> dict:
    """将多种输入格式归一为 {values, x_labels, y_labels}。"""
    if isinstance(data, dict) and "values" in data:
        values = [list(row) for row in data["values"]]
        x_labels = list(data.get("x_labels") or [str(i) for i in range(len(values[0]) if values else 0)])
        y_labels = list(data.get("y_labels") or [str(i) for i in range(len(values))])
        return {"values": values, "x_labels": x_labels, "y_labels": y_labels}

    if isinstance(data, list) and data and isinstance(data[0], dict) and "value" in data[0]:
        # [{"x":..,"y":..,"value":..}] → 透视
        xs, ys = [], []
        for item in data:
            x, y = str(item.get("x")), str(item.get("y"))
            if x not in xs:
                xs.append(x)
            if y not in ys:
                ys.append(y)
        grid = [[0 for _ in xs] for _ in ys]
        for item in data:
            grid[ys.index(str(item.get("y")))][xs.index(str(item.get("x")))] = item.get("value", 0)
        return {"values": grid, "x_labels": xs, "y_labels": ys}

    if isinstance(data, list) and data and isinstance(data[0], list):
        values = [list(row) for row in data]
        return {
            "values": values,
            "x_labels": [str(i) for i in range(len(values[0]) if values else 0)],
            "y_labels": [str(i) for i in range(len(values))],
        }

    raise ValueError("数据格式不支持，请使用二维数组或 {values,x_labels,y_labels}")


def _create_heatmap(data_json: str, title: str = "热力图", theme: str = "default",
                    cmap: str = "viridis", annotate: bool = True,
                    fmt: str = "svg") -> str:
    """生成热力图"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        matrix = _matrix_from_data(parsed["data"])
        values = matrix["values"]
        if not values:
            return "【错误】数据为空"

        fig, ax = plt.subplots(figsize=(8, 6))
        fig.patch.set_facecolor(theme_config["bg_color"])
        ax.set_facecolor(theme_config["bg_color"])

        try:
            im = ax.imshow(values, cmap=cmap, aspect="auto")
        except Exception:
            im = ax.imshow(values, aspect="auto")
        fig.colorbar(im, ax=ax)

        ax.set_xticks(range(len(matrix["x_labels"])))
        ax.set_yticks(range(len(matrix["y_labels"])))
        ax.set_xticklabels(matrix["x_labels"], rotation=45, ha="right",
                           color=theme_config["text_color"])
        ax.set_yticklabels(matrix["y_labels"], color=theme_config["text_color"])

        if annotate:
            flat = [v for row in values for v in row if isinstance(v, (int, float))]
            mid = (max(flat) + min(flat)) / 2 if flat else 0
            for i, row in enumerate(values):
                for j, val in enumerate(row):
                    color = "#000000" if val <= mid else "#ffffff"
                    ax.text(j, i, f"{val:g}" if isinstance(val, (int, float)) else str(val),
                            ha="center", va="center", color=color, fontsize=9)

        ax.set_title(title, color=theme_config["text_color"], fontsize=14)
        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_boxplot(data_json: str, title: str = "箱线图", ylabel: str = "数值",
                    theme: str = "default", fmt: str = "svg") -> str:
    """生成箱线图"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        data = parsed["data"]

        labels, series = [], []
        if isinstance(data, dict):
            for k, v in data.items():
                labels.append(str(k))
                series.append([x for x in v if isinstance(x, (int, float))] if isinstance(v, list) else [v])
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            for i, item in enumerate(data):
                labels.append(str(item.get("label", f"系列{i+1}")))
                series.append([x for x in item.get("values", []) if isinstance(x, (int, float))])
        elif isinstance(data, list) and data and isinstance(data[0], list):
            for i, col in enumerate(data):
                labels.append(f"系列{i+1}")
                series.append([x for x in col if isinstance(x, (int, float))])
        else:
            return "【错误】数据格式不支持，请使用 {\"分组\":[数值...]} 或 [[数值...],...]"

        if not any(series):
            return "【错误】数据为空"

        fig, ax = plt.subplots(figsize=(8, 4.5))
        fig.patch.set_facecolor(theme_config["bg_color"])
        ax.set_facecolor(theme_config["bg_color"])

        bp = ax.boxplot(series, patch_artist=True, showmeans=True)
        for idx, box in enumerate(bp["boxes"]):
            box.set_facecolor(theme_config["colors"][idx % len(theme_config["colors"])])
            box.set_alpha(0.7)
        ax.set_xticklabels(labels, color=theme_config["text_color"])
        ax.set_title(title, color=theme_config["text_color"], fontsize=14)
        ax.set_ylabel(ylabel, color=theme_config["text_color"])
        ax.grid(axis="y", color=theme_config["grid_color"], alpha=0.4)
        ax.tick_params(colors=theme_config["text_color"])

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_funnel(data_json: str, title: str = "漏斗图", theme: str = "default",
                   sort_desc: bool = True, fmt: str = "svg") -> str:
    """生成漏斗图（按阶段数值自上而下收敛）"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    parsed = _parse_data(data_json)
    if not parsed["success"]:
        return parsed["error"]

    try:
        theme_config = _get_theme(theme)
        data = parsed["data"]

        if isinstance(data, dict):
            stages = [(str(k), v) for k, v in data.items() if isinstance(v, (int, float))]
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            stages = [(str(d.get("label", f"阶段{i+1}")), d.get("value", 0))
                      for i, d in enumerate(data) if isinstance(d.get("value", 0), (int, float))]
        else:
            return "【错误】数据格式不支持，请使用 {\"阶段\":值} 或 [{\"label\":..,\"value\":..}]"

        if not stages:
            return "【错误】数据为空"
        if sort_desc:
            stages.sort(key=lambda x: x[1], reverse=True)

        labels = [s[0] for s in stages]
        values = [s[1] for s in stages]
        max_v = max(values) or 1
        n = len(stages)

        fig, ax = plt.subplots(figsize=(7, max(4.0, 0.9 * n + 1.5)))
        fig.patch.set_facecolor(theme_config["bg_color"])
        ax.set_facecolor(theme_config["bg_color"])

        for i, (label, val) in enumerate(stages):
            w_top = val / max_v
            w_bottom = (values[i + 1] / max_v) if i + 1 < n else w_top * 0.6
            y_top = n - i
            y_bottom = n - i - 1
            color = theme_config["colors"][i % len(theme_config["colors"])]
            ax.fill_betweenx([y_top, y_bottom], [-w_top / 2, -w_bottom / 2],
                             [w_top / 2, w_bottom / 2], color=color, alpha=0.85)
            ratio = f"  ({val / values[0] * 100:.1f}%)" if values[0] else ""
            ax.text(0, (y_top + y_bottom) / 2, f"{label}: {val:g}{ratio}",
                    ha="center", va="center", color="#ffffff", fontsize=10)

        ax.set_xlim(-0.6, 0.6)
        ax.set_ylim(0, n)
        ax.axis("off")
        ax.set_title(title, color=theme_config["text_color"], fontsize=14)

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_report(charts: str, title: str = "数据报表",
                   theme: str = "default", fmt: str = "svg") -> str:
    """创建多图表报告"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    try:
        parsed = _parse_data(charts)
        if not parsed["success"]:
            return parsed["error"]

        theme_config = _get_theme(theme)
        chart_list = parsed["data"] if isinstance(parsed["data"], list) else []

        n = len(chart_list)
        if n == 0:
            return "【错误】未指定任何图表"

        # 计算布局
        cols = min(2, n)
        rows = (n + cols - 1) // cols

        fig, axes = plt.subplots(rows, cols, figsize=(8 * cols, 5 * rows))
        fig.patch.set_facecolor(theme_config["bg_color"])

        # 确保 axes 是二维数组
        if rows == 1 and cols == 1:
            axes = [[axes]]
        elif rows == 1:
            axes = [list(axes)]
        elif cols == 1:
            axes = [[ax] for ax in axes]

        for i, chart_config in enumerate(chart_list):
            r, c = divmod(i, cols)
            ax = axes[r][c]
            ax.set_facecolor(theme_config["bg_color"])

            chart_type = chart_config.get("type", "bar")
            chart_data = chart_config.get("data", {})
            chart_title = chart_config.get("title", f"图表{i+1}")
            colors = theme_config["colors"]

            if chart_type == "bar":
                labels = list(chart_data.keys()) if isinstance(chart_data, dict) else []
                values = list(chart_data.values()) if isinstance(chart_data, dict) else []
                ax.bar(labels, values, color=[colors[j % len(colors)] for j in range(len(values))])
            elif chart_type == "line":
                if isinstance(chart_data, dict):
                    ax.plot(list(chart_data.keys()), list(chart_data.values()),
                            marker="o", color=colors[0])
            elif chart_type == "pie":
                if isinstance(chart_data, dict):
                    ax.pie(list(chart_data.values()), labels=list(chart_data.keys()),
                           autopct="%1.1f%%", colors=colors[:len(chart_data)])

            ax.set_title(chart_title, fontsize=12, color=theme_config["text_color"])
            ax.tick_params(colors=theme_config["text_color"])

        # 隐藏多余的子图
        for i in range(n, rows * cols):
            r, c = divmod(i, cols)
            axes[r][c].set_visible(False)

        fig.suptitle(title, fontsize=16, y=0.98, color=theme_config["text_color"])
        plt.tight_layout()

        return _render(fig, plt, title, fmt)
    except Exception as e:
        return f"【报表生成失败】{str(e)}"


# ===================== 会话工作目录 =====================

def _default_base_dir() -> str:
    if os.name == "nt":
        return os.path.join(os.path.expanduser("~"), "mcp-user-data")
    return "/data/mcp-user-data"


def _session_workdir(base_dir: str, user_id: str) -> str:
    """会话工作目录（与 python_executor_tools 保持一致）"""
    safe_uid = "".join(c for c in str(user_id or "default")
                       if c.isalnum() or c in ("-", "_")) or "default"
    workdir = os.path.join(base_dir, "sandbox", safe_uid)
    os.makedirs(workdir, exist_ok=True)
    return workdir


def _svg_save_to_file(svg_content: str, file_path: str) -> dict:
    """将SVG内容保存到文件"""
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(svg_content)
        size = len(svg_content)
        return {"success": True, "path": file_path, "size_bytes": size}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===================== 注册函数 =====================

def register_visualization_tools(mcp, base_dir: str = None):
    """注册数据可视化工具到 MCP 服务器

    Args:
        base_dir: 用户数据根目录；viz_svg_to_file 的落盘限定在 {base_dir}/sandbox/{user_id}
    """
    _base_dir = base_dir or _default_base_dir()

    @mcp.tool(
        name="viz_line_chart",
        description='生成折线图。Args: data_json(JSON数据,支持数组或[{label,values}]多系列格式), title(标题), xlabel(X轴标签), ylabel(Y轴标签), theme(主题:default/dark/colorblind), format(输出格式:svg/png,默认svg)'
    )
    def viz_line_chart(data_json: str, title: str = "折线图", xlabel: str = "X",
                       ylabel: str = "Y", theme: str = "default",
                       format: str = "svg") -> str:
        return _create_line_chart(data_json, title, xlabel, ylabel, theme, format)

    @mcp.tool(
        name="viz_bar_chart",
        description='生成柱状图。Args: data_json(JSON数据,{"标签":值}或[{labels,values}]), title(标题), xlabel/ylabel(轴标签), theme(主题), horizontal(是否水平), format(输出格式:svg/png)'
    )
    def viz_bar_chart(data_json: str, title: str = "柱状图", xlabel: str = "类别",
                      ylabel: str = "数值", theme: str = "default",
                      horizontal: bool = False, format: str = "svg") -> str:
        return _create_bar_chart(data_json, title, xlabel, ylabel, theme, horizontal, format)

    @mcp.tool(
        name="viz_pie_chart",
        description='生成饼图。Args: data_json(JSON数据,{"名称":数值}), title(标题), theme(主题), show_percent(是否显示百分比), format(输出格式:svg/png)'
    )
    def viz_pie_chart(data_json: str, title: str = "饼图",
                      theme: str = "default", show_percent: bool = True,
                      format: str = "svg") -> str:
        return _create_pie_chart(data_json, title, theme, show_percent, format)

    @mcp.tool(
        name="viz_scatter_chart",
        description='生成散点图。Args: data_json(JSON数据,[[x1,y1],[x2,y2]]或[{x,y,label}多系列]), title(标题), xlabel/ylabel(轴标签), theme(主题), format(输出格式:svg/png)'
    )
    def viz_scatter_chart(data_json: str, title: str = "散点图", xlabel: str = "X",
                          ylabel: str = "Y", theme: str = "default",
                          format: str = "svg") -> str:
        return _create_scatter_chart(data_json, title, xlabel, ylabel, theme, format)

    @mcp.tool(
        name="viz_heatmap",
        description='生成热力图。Args: data_json(JSON数据,二维数组[[..],[..]] 或 {values:[[..]],x_labels:[..],y_labels:[..]}), title(标题), theme(主题), cmap(色带,如viridis/Blues/RdYlGn), annotate(是否标注数值), format(输出格式:svg/png)'
    )
    def viz_heatmap(data_json: str, title: str = "热力图", theme: str = "default",
                    cmap: str = "viridis", annotate: bool = True,
                    format: str = "svg") -> str:
        return _create_heatmap(data_json, title, theme, cmap, annotate, format)

    @mcp.tool(
        name="viz_boxplot",
        description='生成箱线图。Args: data_json(JSON数据,{"分组":[数值...]} 或 [[数值...],...]), title(标题), ylabel(Y轴标签), theme(主题), format(输出格式:svg/png)'
    )
    def viz_boxplot(data_json: str, title: str = "箱线图", ylabel: str = "数值",
                    theme: str = "default", format: str = "svg") -> str:
        return _create_boxplot(data_json, title, ylabel, theme, format)

    @mcp.tool(
        name="viz_funnel",
        description='生成漏斗图。Args: data_json(JSON数据,{"阶段":数值} 或 [{"label":..,"value":..}]), title(标题), theme(主题), sort_desc(是否按数值降序), format(输出格式:svg/png)'
    )
    def viz_funnel(data_json: str, title: str = "漏斗图", theme: str = "default",
                   sort_desc: bool = True, format: str = "svg") -> str:
        return _create_funnel(data_json, title, theme, sort_desc, format)

    @mcp.tool(
        name="viz_create_report",
        description='创建多图表报表。Args: charts(JSON数组,[{type,data,title}...],type支持bar/line/pie), title(报表标题), theme(主题), format(输出格式:svg/png)'
    )
    def viz_create_report(charts: str, title: str = "数据报表",
                          theme: str = "default", format: str = "svg") -> str:
        return _create_report(charts, title, theme, format)

    @mcp.tool(
        name="viz_svg_to_file",
        description="将SVG图表内容保存为服务器.svg文件（限定在会话工作目录内），并返回Base64编码内容。Args: svg_content(SVG图表文本内容,必填), file_path(相对会话工作目录的保存路径), user_id(当前登录用户ID,默认default)"
    )
    def viz_svg_to_file(svg_content: str, file_path: str,
                        user_id: str = "default") -> str:
        workdir = _session_workdir(_base_dir, user_id)
        safe_path = _resolve_output_path(file_path, workdir)
        result = _svg_save_to_file(svg_content, safe_path)
        b64 = base64.b64encode(svg_content.encode("utf-8")).decode("ascii")
        if result["success"]:
            return json.dumps({
                "message": "SVG已保存",
                "path": result["path"],
                "size_bytes": result["size_bytes"],
                "download_base64": b64,
                "usage": "将 download_base64 解码后保存为 .svg 文件",
            }, ensure_ascii=False, indent=2)
        return f"【保存失败】{result['error']}"

    logger.info("数据可视化工具已注册（SVG/PNG，中文字体注入）")
