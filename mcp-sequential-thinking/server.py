"""
mcp-sequential-thinking - Sequential Thinking MCP Server

基于结构化推理链的多步骤思考工具。帮助 LLM 在复杂问题上进行
分步骤、可回溯、可修正的推理过程。
"""
from mcp.server.fastmcp import FastMCP
import json
import time
import uuid
import sys

# 创建服务器
mcp = FastMCP("mcp-sequential-thinking", host="0.0.0.0", port=19103, json_response=True)

# =====================================================================
# 会话状态存储：session_id -> 思考历史
# =====================================================================
_sessions = {}

MAX_HISTORY = 100  # 每个会话最多保留的思考步骤


@mcp.tool()
async def sequential_thinking(
    thought: str,
    thought_number: int = 1,
    total_thoughts: int = 0,
    next_thought_needed: bool = True,
    is_revision: bool = False,
    revises_thought: int = 0,
    branch_from_thought: int = 0,
    branch_id: str = "",
    needs_more_thoughts: bool = False,
    session_id: str = "",
) -> str:
    """结构化多步骤推理工具。帮助在复杂任务上分步深度思考。

    每次调用记录一个思考步骤，支持修正之前步骤、创建分支。

    Args:
        thought: 当前思考内容（必填，记录具体的推理内容）
        thought_number: 当前思考编号（从1开始）
        total_thoughts: 预估的总思考步数（可调整）
        next_thought_needed: 是否需要继续思考（True=继续，False=推理结束）
        is_revision: 是否为修正之前的某个步骤
        revises_thought: 修正的是第几步（is_revision=True 时有效）
        branch_from_thought: 从第几步分支出新路径
        branch_id: 分支标识（多方案比较时使用）
        needs_more_thoughts: 是否需要增加 total_thoughts
        session_id: 会话ID（空则自动生成，同一个任务传入相同ID可保持上下文）

    Returns:
        JSON: 当前思考链摘要，包含已完成步数、下一步建议
    """
    global _sessions

    sid = session_id or str(uuid.uuid4())[:8]
    if sid not in _sessions:
        _sessions[sid] = {
            "started_at": time.time(),
            "thoughts": [],
            "branches": {},
            "revisions": {},
        }

    session = _sessions[sid]
    entry = {
        "thought": thought,
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "is_revision": is_revision,
        "revises_thought": revises_thought,
        "branch_from_thought": branch_from_thought,
        "branch_id": branch_id,
        "timestamp": time.time(),
    }

    # 处理修正
    if is_revision and revises_thought > 0:
        session["revisions"][str(revises_thought)] = entry

    # 记录分支
    if branch_id:
        if branch_id not in session["branches"]:
            session["branches"][branch_id] = []
        session["branches"][branch_id].append(entry)

    session["thoughts"].append(entry)

    # 限制历史长度
    if len(session["thoughts"]) > MAX_HISTORY:
        session["thoughts"] = session["thoughts"][-MAX_HISTORY:]

    # 构建返回
    chain_summary = []
    for t in session["thoughts"]:
        prefix = "🔄" if t["is_revision"] else "💭"
        if t["branch_id"]:
            prefix = f"🔀[{t['branch_id']}]"
        chain_summary.append(f"{prefix} 第{t['thought_number']}步: {t['thought'][:80]}{'...' if len(t['thought']) > 80 else ''}")

    result = {
        "session_id": sid,
        "total_steps": len(session["thoughts"]),
        "current_step": thought_number,
        "estimated_total": total_thoughts,
        "has_revisions": len(session["revisions"]) > 0,
        "branches": list(session["branches"].keys()) if session["branches"] else [],
        "next_thought_needed": next_thought_needed,
        "suggestion": "",
        "chain": chain_summary,
    }

    # 给出建议
    if next_thought_needed:
        if needs_more_thoughts:
            result["suggestion"] = (
                f"当前已记录 {thought_number} 步。"
                f"建议继续第 {thought_number + 1} 步，"
                f"预估总共需要 {max(total_thoughts + 3, thought_number + 2)} 步。"
            )
        else:
            result["suggestion"] = f"继续第 {thought_number + 1} 步。"
    else:
        result["suggestion"] = "推理完成，可以总结结论了。"

    return json.dumps(result, ensure_ascii=False, indent=2)


print("[MCP Server] mcp-sequential-thinking 已就绪，端口: 19103", file=sys.stderr)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
