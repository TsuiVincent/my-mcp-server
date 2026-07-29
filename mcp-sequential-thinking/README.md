# mcp-sequential-thinking - Sequential Thinking MCP Server

结构化多步骤推理工具。帮助 LLM 在复杂问题上进行分步骤、可回溯、可修正的推理。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:8009`，使用 `streamable-http` 传输协议。

## 工具列表 (1个)

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `sequential_thinking` | 结构化多步推理 | `thought`, `thought_number`, `total_thoughts`, `next_thought_needed`, `is_revision`, `revises_thought`, `branch_from_thought`, `branch_id`, `session_id` |

### 使用场景

- 复杂多步任务拆解（如设计系统架构、分析 Bug 根因）
- 需要回溯修正的推理（如代码审查发现遗漏）
- 多方案对比（使用 branch_id 分叉推理）
- 深度分析（逐步深入、逐层展开）

### 使用示例

```
第1步：分析问题范围 → sequential_thinking(thought="...", thought_number=1, total_thoughts=5)
第2步：列出可能原因 → sequential_thinking(thought="...", thought_number=2, total_thoughts=5)
第3步：逐一验证假设 → sequential_thinking(thought="...", thought_number=3, total_thoughts=5)
// 发现第2步遗漏 → sequential_thinking(thought="补...", thought_number=4, is_revision=True, revises_thought=2)
第5步：得出结论      → sequential_thinking(thought="...", thought_number=5, next_thought_needed=False)
```

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0
```
