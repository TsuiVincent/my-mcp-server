# -*- coding: utf-8 -*-
"""可视化工具数据格式回归测试。

背景：前端实测发现 LLM 以 {"labels": [...], "values": [...]}（柱状图格式）
调用 viz_line_chart 时，折线图所有绘图分支被跳过且不报错，产出「空轴图」
却标记成功。本文件回归：
1. 折线图/散点图/饼图对 dict 格式（labels/values、x/y）的支持；
2. 不支持的格式必须显式报错，禁止静默输出空图。
"""
import json
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tools.visualization_tools import (
    _create_line_chart,
    _create_pie_chart,
    _create_scatter_chart,
)


def _assert_png_ok(result: str) -> dict:
    assert '【错误】' not in result, result
    assert '【图表生成失败】' not in result, result
    payload = json.loads(result)
    assert payload.get('format') == 'png'
    assert payload.get('size_bytes', 0) > 0
    assert payload.get('base64_data')
    return payload


# ── 折线图 ──

def test_line_accepts_labels_values_dict():
    """实测事故格式：LLM 以柱状图同款 dict 调用折线图，必须画出数据线。"""
    r = _create_line_chart(
        json.dumps({'labels': ['1月', '2月', '3月'], 'values': [120, 135, 128]}),
        title='销售额', fmt='png')
    _assert_png_ok(r)


def test_line_accepts_xy_dict():
    r = _create_line_chart(json.dumps({'x': [1, 2, 3], 'y': [4, 5, 6]}), fmt='png')
    _assert_png_ok(r)


def test_line_accepts_key_value_dict():
    r = _create_line_chart(json.dumps({'1月': 120, '2月': 135}), fmt='png')
    _assert_png_ok(r)


def test_line_accepts_labels_values_single_series_list():
    r = _create_line_chart(
        json.dumps([{'labels': ['a', 'b'], 'values': [1, 2]}]), fmt='png')
    _assert_png_ok(r)


def test_line_accepts_plain_number_list():
    r = _create_line_chart(json.dumps([1, 2, 3]), fmt='png')
    _assert_png_ok(r)


def test_line_accepts_point_pairs():
    r = _create_line_chart(json.dumps([[1, 2], [2, 4], [3, 9]]), fmt='png')
    _assert_png_ok(r)


def test_line_accepts_multi_series():
    r = _create_line_chart(json.dumps([
        {'label': '销售额', 'values': [1, 2, 3]},
        {'label': '利润', 'values': [4, 5, 6]},
    ]), fmt='png')
    _assert_png_ok(r)


def test_line_unsupported_format_returns_error_not_empty_png():
    """回归核心：不支持的格式必须显式报错，禁止静默渲染空轴图。"""
    r = _create_line_chart(json.dumps({'foo': 'bar'}), fmt='png')
    assert '【错误】数据格式不支持' in r
    assert 'base64_data' not in r


# ── 散点图 ──

def test_scatter_accepts_xy_dict():
    r = _create_scatter_chart(json.dumps({'x': [1, 2, 3], 'y': [4, 5, 6]}), fmt='png')
    _assert_png_ok(r)


def test_scatter_accepts_values_alias():
    r = _create_scatter_chart(
        json.dumps({'labels': ['a', 'b', 'c'], 'values': [3, 1, 2]}), fmt='png')
    _assert_png_ok(r)


def test_scatter_accepts_point_pairs():
    r = _create_scatter_chart(json.dumps([[1, 2], [2, 4]]), fmt='png')
    _assert_png_ok(r)


def test_scatter_unsupported_format_returns_error():
    r = _create_scatter_chart(json.dumps([1, 2, 3]), fmt='png')
    assert '【错误】数据格式不支持' in r


# ── 饼图 ──

def test_pie_accepts_labels_values_single_series_list():
    r = _create_pie_chart(
        json.dumps([{'labels': ['A', 'B', 'C'], 'values': [3, 2, 1]}]), fmt='png')
    _assert_png_ok(r)


def test_pie_accepts_key_value_dict():
    r = _create_pie_chart(json.dumps({'A': 3, 'B': 2}), fmt='png')
    _assert_png_ok(r)


def test_pie_accepts_label_value_list():
    r = _create_pie_chart(
        json.dumps([{'label': 'A', 'value': 3}, {'label': 'B', 'value': 2}]),
        fmt='png')
    _assert_png_ok(r)
