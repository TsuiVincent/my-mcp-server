import os
import sqlite3
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction


def get_user_sqlite_path(base_dir: str, user_id: str | int) -> str:
    """获取当前用户专属 SQLite 数据库路径"""
    return os.path.join(base_dir, "user_sqlite", f"{user_id}_private.db")


def get_user_chroma_path(base_dir: str, user_id: str | int) -> str:
    """获取当前用户专属 Chroma 向量库路径"""
    return os.path.join(base_dir, "user_chroma", f"{user_id}_chroma_db")


def init_user_dirs(base_dir: str):
    """初始化用户数据目录"""
    dirs = [
        os.path.join(base_dir, "raw_files"),
        os.path.join(base_dir, "user_sqlite"),
        os.path.join(base_dir, "user_chroma")
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


# ===================== 工具1：用户私有 SQL 查询 =====================
def _user_private_sql_query(base_dir: str, user_id: str, sql: str) -> str:
    """内部实现：查询用户私有结构化数据"""
    deny_words = {"drop", "alter", "insert", "delete", "update", "create", "truncate"}
    sql_lower = sql.lower()
    for word in deny_words:
        if word in sql_lower:
            return f"【安全拦截】禁止执行 {word} 相关操作，仅允许查询数据。"

    db_path = get_user_sqlite_path(base_dir, user_id)
    if not os.path.exists(db_path):
        return "提示：你暂未上传任何表格/JSON结构化数据。"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(sql)

        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "查询结果：无匹配数据"

        result_lines = ["查询结果："]
        result_lines.append(" | ".join(cols))
        for row in rows:
            result_lines.append(" | ".join(str(item) for item in row))
        return "\n".join(result_lines)

    except Exception as e:
        return f"SQL执行异常：{str(e)}"


# ===================== 工具2：用户私有 RAG 文档检索 =====================
def _user_private_rag_search(base_dir: str, user_id: str, query: str, top_k: int = 3) -> str:
    """内部实现：检索用户私有文档知识库"""
    chroma_path = get_user_chroma_path(base_dir, user_id)
    if not os.path.exists(chroma_path):
        return "提示：你暂未上传任何文档类知识库。"

    try:
        embedding_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_or_create_collection(
            name="docs",
            embedding_function=embedding_fn
        )

        results = collection.query(
            query_texts=[query],
            n_results=top_k
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents:
            return "未在你的私有文档库中找到相关内容。"

        output = ["【私有知识库参考内容】"]
        for idx, doc in enumerate(documents):
            meta = metadatas[idx] if metadatas else {}
            source = meta.get("source", "未知文档")
            output.append(f"\n片段{idx + 1}（来源：{source}）：")
            output.append(doc)

        return "\n".join(output)

    except Exception as e:
        return f"文档检索异常：{str(e)}"


# ===================== 注册函数：供 server.py 调用 =====================
def register_user_kb_tools(mcp, base_dir: str):
    """注册用户知识库相关工具到 MCP 服务器"""
    init_user_dirs(base_dir)

    @mcp.tool(
        name="user_private_sql_query",
        description="查询当前用户自己上传的Excel、CSV、JSON结构化数据表。仅支持SELECT查询，禁止修改数据。Args: user_id(当前登录用户ID), sql(SELECT查询语句)"
    )
    def user_private_sql_query(user_id: str, sql: str) -> str:
        return _user_private_sql_query(base_dir, user_id, sql)

    @mcp.tool(
        name="user_private_rag_search",
        description="检索当前用户自己上传的PDF、MD、TXT等文档知识库，获取相关参考内容。Args: user_id(当前登录用户ID), query(检索关键词), top_k(返回片段数,默认3)"
    )
    def user_private_rag_search(user_id: str, query: str, top_k: int = 3) -> str:
        return _user_private_rag_search(base_dir, user_id, query, top_k)