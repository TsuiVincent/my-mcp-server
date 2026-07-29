"""
内部知识库检索工具
基于内网文档的全文检索系统，支持关键词搜索、内容摘要、相关度排序。
支持文档格式：txt、pdf、md、html、csv、json等。

工具列表：
- kb_index_directory: 索引指定目录下的文档
- kb_search: 全文关键词搜索
- kb_search_with_context: 带上下文的搜索
- kb_list_documents: 列出已索引文档
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from collections import Counter

logger = logging.getLogger(__name__)

# ===================== 知识库存储 =====================

_file_index: Dict[str, dict] = {}

_SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".html", ".htm",
    ".xml", ".log", ".py", ".js", ".ts", ".java",
    ".go", ".rs", ".cpp", ".c", ".h", ".conf",
    ".ini", ".cfg", ".yaml", ".yml", ".toml", ".sql"
}

_MAX_SEARCH_RESULTS = 20
_CONTEXT_WINDOW = 80  # 搜索结果上下文字符数


# ===================== 文件读取 =====================

def _read_file_content(file_path: str) -> Optional[str]:
    """读取文件内容（支持多种编码）"""
    encodings = ["utf-8", "gbk", "gb2312", "latin-1", "cp1252"]
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, IOError):
            continue
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _compute_tf(content: str) -> Counter:
    """计算词频"""
    words = re.findall(r'[\w\u4e00-\u9fff]+', content.lower())
    return Counter(words)


def _compute_search_score(query: str, content: str) -> float:
    """计算搜索相关度（TF-IDF简化版）"""
    query_terms = set(query.lower().split())
    if not query_terms:
        return 0.0

    content_lower = content.lower()
    total_score = 0.0

    # 全句匹配加分
    if query.lower() in content_lower:
        total_score += 10.0

    for term in query_terms:
        count = content_lower.count(term)
        if count > 0:
            # 词频加权
            total_score += 1.0 + (count * 0.5)
            # 标题中的词加权
            first_line = content_lower.split('\n')[0]
            if term in first_line:
                total_score += 2.0

    # 长度惩罚
    length_factor = min(1.0, 5000.0 / max(len(content), 1))
    return total_score * length_factor


def _generate_preview(content: str, max_length: int = 200) -> str:
    """生成内容预览"""
    cleaned = re.sub(r'\s+', ' ', content).strip()
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length] + "..."


def _extract_context(content: str, keyword: str,
                     context_size: int = _CONTEXT_WINDOW) -> list:
    """提取关键词上下文"""
    contexts = []
    content_lower = content.lower()
    keyword_lower = keyword.lower()

    start = 0
    while True:
        pos = content_lower.find(keyword_lower, start)
        if pos == -1 or len(contexts) >= 5:
            break

        ctx_start = max(0, pos - context_size)
        ctx_end = min(len(content), pos + len(keyword) + context_size)

        snippet = content[ctx_start:ctx_end].strip()
        # 添加省略号标记
        if ctx_start > 0:
            snippet = "..." + snippet
        if ctx_end < len(content):
            snippet = snippet + "..."

        contexts.append(snippet)
        start = pos + len(keyword)

    return contexts


# ===================== 索引管理 =====================

def _index_directory(directory: str, recursive: bool = True) -> str:
    """索引指定目录下的文档"""
    if not os.path.isdir(directory):
        return f"【错误】目录不存在: {directory}"

    indexed_count = 0
    error_count = 0
    skipped_count = 0

    pattern = "**/*" if recursive else "*"
    for file_path in Path(directory).glob(pattern):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        if ext not in _SUPPORTED_EXTENSIONS:
            skipped_count += 1
            continue

        abs_path = str(file_path.resolve())

        # 跳过已索引且未修改的文件
        mtime = os.path.getmtime(abs_path)
        if abs_path in _file_index:
            if _file_index[abs_path].get("mtime") == mtime:
                continue

        content = _read_file_content(abs_path)
        if content is None:
            error_count += 1
            continue

        stat = os.stat(abs_path)
        _file_index[abs_path] = {
            "title": file_path.name,
            "path": abs_path,
            "size": stat.st_size,
            "mtime": mtime,
            "modified": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "preview": _generate_preview(content),
            "content_length": len(content),
            "word_count": len(re.findall(r'\w+', content)),
            "ext": ext
        }
        indexed_count += 1

    return (
        f"【索引完成】\n"
        f"  目录: {directory}\n"
        f"  索引: {indexed_count} 个文件\n"
        f"  跳过: {skipped_count} 个文件（不支持的格式）\n"
        f"  失败: {error_count} 个文件\n"
        f"  索引总数: {len(_file_index)} 个文件"
    )


def _search_knowledge(query: str, top_k: int = 10,
                       file_pattern: str = "", directory: str = "") -> str:
    """全文关键词搜索"""
    if not _file_index:
        return "【提示】知识库为空，请先使用 kb_index_directory 索引文档。"

    if not query.strip():
        return "【提示】请输入搜索关键词"

    results = []
    for file_path, info in _file_index.items():
        # 目录过滤
        if directory and not file_path.startswith(directory):
            continue
        # 文件模式过滤
        if file_pattern:
            if not Path(file_path).match(file_pattern):
                continue

        content = _read_file_content(file_path)
        if content is None:
            continue

        score = _compute_search_score(query, content)
        if score > 0:
            results.append({
                "path": file_path,
                "title": info["title"],
                "score": score,
                "preview": info["preview"],
                "modified": info["modified"],
                "size": info.get("size", 0)
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = results[:min(top_k, _MAX_SEARCH_RESULTS)]

    if not top_results:
        return f"【搜索结果】未找到与 '{query}' 相关的内容。"

    lines = [f"【搜索结果: '{query}'】共找到 {len(results)} 条，显示前 {len(top_results)} 条:\n"]
    for i, r in enumerate(top_results, 1):
        lines.append(f"{i}. [{r['title']}] (相关度: {r['score']:.1f})")
        lines.append(f"   路径: {r['path']}")
        lines.append(f"   修改: {r['modified']}")
        lines.append(f"   预览: {r['preview']}")
        lines.append("")

    return "\n".join(lines)


def _search_with_context(query: str, top_k: int = 3) -> str:
    """带上下文的搜索"""
    if not _file_index:
        return "【提示】知识库为空，请先使用 kb_index_directory 索引文档。"

    results = []
    for file_path, info in _file_index.items():
        content = _read_file_content(file_path)
        if content is None or query.lower() not in content.lower():
            continue

        score = _compute_search_score(query, content)
        contexts = _extract_context(content, query)

        results.append({
            "path": file_path,
            "title": info["title"],
            "score": score,
            "contexts": contexts,
            "modified": info["modified"]
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = results[:top_k]

    if not top_results:
        return f"【搜索结果】未找到与 '{query}' 相关的内容。"

    lines = [f"【上下文搜索: '{query}'】\n"]
    for i, r in enumerate(top_results, 1):
        lines.append(f"--- {i}. {r['title']} (相关度: {r['score']:.1f}) ---")
        lines.append(f"路径: {r['path']}")
        lines.append(f"修改: {r['modified']}")
        for j, ctx in enumerate(r["contexts"], 1):
            lines.append(f"\n  上下文 {j}:")
            lines.append(f"    {ctx}")
        lines.append("")

    return "\n".join(lines)


def _list_documents(directory: str = "",
                     file_pattern: str = "") -> str:
    """列出已索引文档"""
    if not _file_index:
        return "【提示】知识库为空"

    files = []
    for file_path, info in _file_index.items():
        if directory and not file_path.startswith(directory):
            continue
        if file_pattern and not Path(file_path).match(file_pattern):
            continue
        files.append(info)

    files.sort(key=lambda x: x["title"])

    lines = [f"【已索引文档】共 {len(files)} 个文件:\n"]
    for i, f in enumerate(files, 1):
        size_kb = f.get("size", 0) / 1024
        lines.append(
            f"{i}. {f['title']} ({size_kb:.1f}KB, {f.get('word_count', 0)}词) "
            f"修改: {f['modified']}"
        )

    return "\n".join(lines)


def _clear_index() -> str:
    """清空索引"""
    count = len(_file_index)
    _file_index.clear()
    return f"【已清空】索引已重置，共清除 {count} 个文档索引"


# ===================== 注册函数 =====================

def register_knowledge_search_tools(mcp):
    """注册知识库检索工具到 MCP 服务器"""

    @mcp.tool(
        name="kb_index_directory",
        description="索引指定目录下的文档(txt/md/csv/json/html/log/代码文件等)，建立全文搜索索引。Args: directory(目录路径,必填), recursive(是否递归子目录,默认true)"
    )
    def kb_index_directory(directory: str, recursive: bool = True) -> str:
        return _index_directory(directory, recursive)

    @mcp.tool(
        name="kb_search",
        description="全文关键词搜索已索引文档，按相关度排序返回结果。Args: query(搜索关键词,必填), top_k(返回条数,默认10), file_pattern(文件模式过滤如*.md,可选), directory(目录过滤,可选)"
    )
    def kb_search(query: str, top_k: int = 10,
                  file_pattern: str = "", directory: str = "") -> str:
        return _search_knowledge(query, top_k, file_pattern, directory)

    @mcp.tool(
        name="kb_search_with_context",
        description="带上下文片段的深度搜索，显示关键词附近内容。Args: query(搜索关键词,必填), top_k(返回条数,默认3)"
    )
    def kb_search_with_context(query: str, top_k: int = 3) -> str:
        return _search_with_context(query, top_k)

    @mcp.tool(
        name="kb_list_documents",
        description="列出所有已索引文档。Args: directory(按目录过滤,可选), file_pattern(按文件模式过滤,可选)"
    )
    def kb_list_documents(directory: str = "", file_pattern: str = "") -> str:
        return _list_documents(directory, file_pattern)

    @mcp.tool(
        name="kb_clear_index",
        description="清空所有文档索引"
    )
    def kb_clear_index() -> str:
        return _clear_index()

    logger.info("知识库检索工具已注册")
