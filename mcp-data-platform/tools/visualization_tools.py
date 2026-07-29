"""
数据可视化与报表工具
支持多种图表类型（折线图、柱状图、饼图、散点图、热力图等），实现数据导入、
图表生成及报表导出功能，支持自定义模板。图表以SVG矢量格式返回，
可直接嵌入HTML预览，缩放无损，支持CSS样式定制。

工具列表：
- viz_line_chart: 生成折线图 (SVG)
- viz_bar_chart: 生成柱状图 (SVG)
- viz_pie_chart: 生成饼图 (SVG)
- viz_scatter_chart: 生成散点图 (SVG)
- viz_create_report: 创建多图表报表 (SVG)
- viz_svg_to_file: 将SVG图表保存为文件
"""

import os
import io
import json
import base64
import logging
import tempfile
import xml.etree.ElementTree as ET
from typing import List

logger = logging.getLogger(__name__)

# 设置matplotlib非交互后端
os.environ["MPLBACKEND"] = "Agg"


def _check_matplotlib():
    """检查并设置matplotlib"""
    try:
        import matplotlib
        matplotlib.use("Agg")  # 非交互后端
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


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


def _parse_list(data_str: str) -> List[float]:
    """解析逗号分隔的数字列表"""
    items = [x.strip() for x in data_str.split(",") if x.strip()]
    result = []
    for item in items:
        try:
            result.append(float(item))
        except ValueError:
            pass
    return result


# ===================== 图表生成 =====================

def _create_line_chart(data_json: str, title: str = "折线图",
                       xlabel: str = "X", ylabel: str = "Y",
                       theme: str = "default") -> str:
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

        svg = _fig_to_svg(fig)
        plt.close(fig)
        return f"【{title}】\n{SVG_START}\n{svg}\n{SVG_END}"
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_bar_chart(data_json: str, title: str = "柱状图",
                      xlabel: str = "类别", ylabel: str = "数值",
                      theme: str = "default", horizontal: bool = False) -> str:
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

        svg = _fig_to_svg(fig)
        plt.close(fig)
        return f"【{title}】\n{SVG_START}\n{svg}\n{SVG_END}"
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_pie_chart(data_json: str, title: str = "饼图",
                      theme: str = "default",
                      show_percent: bool = True) -> str:
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

        svg = _fig_to_svg(fig)
        plt.close(fig)
        return f"【{title}】\n{SVG_START}\n{svg}\n{SVG_END}"
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_scatter_chart(data_json: str, title: str = "散点图",
                          xlabel: str = "X", ylabel: str = "Y",
                          theme: str = "default") -> str:
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

        svg = _fig_to_svg(fig)
        plt.close(fig)
        return f"【{title}】\n{SVG_START}\n{svg}\n{SVG_END}"
    except Exception as e:
        return f"【图表生成失败】{str(e)}"


def _create_report(charts: str, title: str = "数据报表",
                   theme: str = "default") -> str:
    """创建多图表报告"""
    plt = _check_matplotlib()
    if plt is None:
        return "【错误】matplotlib 库未安装。"

    try:
        parsed = _parse_data(charts)
        if not parsed["success"]:
            return parsed["error"]

        chart_list = parsed["data"] if isinstance(parsed["data"], list) else []

        n = len(chart_list)
        if n == 0:
            return "【错误】未指定任何图表"

        # 计算布局
        cols = min(2, n)
        rows = (n + cols - 1) // cols

        fig, axes = plt.subplots(rows, cols, figsize=(8 * cols, 5 * rows))
        fig.patch.set_facecolor("white")

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

            chart_type = chart_config.get("type", "bar")
            chart_data = chart_config.get("data", {})
            chart_title = chart_config.get("title", f"图表{i+1}")

            if chart_type == "bar":
                labels = list(chart_data.keys()) if isinstance(chart_data, dict) else []
                values = list(chart_data.values()) if isinstance(chart_data, dict) else []
                ax.bar(labels, values, color="#4e79a7")
            elif chart_type == "line":
                if isinstance(chart_data, dict):
                    ax.plot(list(chart_data.keys()), list(chart_data.values()), marker="o")
            elif chart_type == "pie":
                if isinstance(chart_data, dict):
                    ax.pie(list(chart_data.values()), labels=list(chart_data.keys()), autopct="%1.1f%%")

            ax.set_title(chart_title, fontsize=12)

        # 隐藏多余的子图
        for i in range(n, rows * cols):
            r, c = divmod(i, cols)
            axes[r][c].set_visible(False)

        fig.suptitle(title, fontsize=16, y=0.98)
        plt.tight_layout()

        svg = _fig_to_svg(fig)
        plt.close(fig)
        return f"【报表: {title}】包含 {n} 个图表\n{SVG_START}\n{svg}\n{SVG_END}"
    except Exception as e:
        return f"【报表生成失败】{str(e)}"


# ===================== 注册函数 =====================

def register_visualization_tools(mcp):
    """注册数据可视化工具到 MCP 服务器（输出SVG矢量格式）"""

    @mcp.tool(
        name="viz_line_chart",
        description='生成折线图(SVG矢量)。Args: data_json(JSON数据,支持数组或[{label,values}]多系列格式), title(标题), xlabel(X轴标签), ylabel(Y轴标签), theme(主题:default/dark/colorblind)'
    )
    def viz_line_chart(data_json: str, title: str = "折线图", xlabel: str = "X",
                       ylabel: str = "Y", theme: str = "default") -> str:
        return _create_line_chart(data_json, title, xlabel, ylabel, theme)

    @mcp.tool(
        name="viz_bar_chart",
        description='生成柱状图(SVG矢量)。Args: data_json(JSON数据,{"标签":值}或[{labels,values}]), title(标题), xlabel/ylabel(轴标签), theme(主题), horizontal(是否水平)'
    )
    def viz_bar_chart(data_json: str, title: str = "柱状图", xlabel: str = "类别",
                      ylabel: str = "数值", theme: str = "default",
                      horizontal: bool = False) -> str:
        return _create_bar_chart(data_json, title, xlabel, ylabel, theme, horizontal)

    @mcp.tool(
        name="viz_pie_chart",
        description='生成饼图(SVG矢量)。Args: data_json(JSON数据,{"名称":数值}), title(标题), theme(主题), show_percent(是否显示百分比)'
    )
    def viz_pie_chart(data_json: str, title: str = "饼图",
                      theme: str = "default", show_percent: bool = True) -> str:
        return _create_pie_chart(data_json, title, theme, show_percent)

    @mcp.tool(
        name="viz_scatter_chart",
        description='生成散点图(SVG矢量)。Args: data_json(JSON数据,[[x1,y1],[x2,y2]]或[{x,y,label}多系列]), title(标题), xlabel/ylabel(轴标签), theme(主题)'
    )
    def viz_scatter_chart(data_json: str, title: str = "散点图", xlabel: str = "X",
                          ylabel: str = "Y", theme: str = "default") -> str:
        return _create_scatter_chart(data_json, title, xlabel, ylabel, theme)

    @mcp.tool(
        name="viz_create_report",
        description='创建多图表报表(SVG矢量)。Args: charts(JSON数组,[{type,data,title}...]), title(报表标题), theme(主题)'
    )
    def viz_create_report(charts: str, title: str = "数据报表",
                          theme: str = "default") -> str:
        return _create_report(charts, title, theme)

    @mcp.tool(
        name="viz_svg_to_file",
        description="将SVG图表内容保存为服务器.svg文件，并返回Base64编码内容。Args: svg_content(SVG图表文本内容,必填), file_path(服务器保存路径,必填)"
    )
    def viz_svg_to_file(svg_content: str, file_path: str) -> str:
        result = _svg_save_to_file(svg_content, file_path)
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

    logger.info("数据可视化工具已注册（SVG矢量格式）")
