# 平台端排查指南 —— 智能填表问题

## 问题现象

- `file_upload` 返回成功：`{"server_path": "/data/uploads/个人简历空表.docx", "file_size": 5596}`
- `smart_fill_form` 报错：`Package not found at '/data/uploads/个人简历空表.docx'`
- `fill_word_form_base64` 也报同样的错

> **注意**："Package not found" 不是文件不存在，而是文件**存在但内容不是有效的 .docx**（python-docx 打不开）。

---

## 前端排查点

### 1. 检查文件是否真的是 .docx 格式

**操作**：在用户上传文件时，前端 `console.log(file.type, file.name)`

```javascript
const handleUpload = (file) => {
  console.log("文件类型:", file.type);
  console.log("文件名:", file.name);
  // 正确应为: file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  // 如果 file.type === "application/msword"，说明是旧版 .doc 格式
};
```

**判断**：
- ✅ `application/vnd.openxmlformats-officedocument.wordprocessingml.document` → 正确的 .docx
- ❌ `application/msword` → 旧版 .doc，MCP 服务器打不开
- ❌ `application/pdf`、`image/png` 等 → 完全传错了文件

**修复**：如果用户上传了 .doc，前端应提示"请另存为 .docx 格式后重新上传"。

### 2. 检查 Base64 生成逻辑

**操作**：在调用 `smart_fill_form` 之前，打印 Base64 的前 100 个字符

```javascript
const reader = new FileReader();
reader.readAsDataURL(file);
reader.onload = () => {
  const base64 = reader.result;  // data:application/...;base64,UEsDB...
  console.log("Base64 前缀:", base64.substring(0, 100));
  console.log("Base64 总长度:", base64.length);

  // 传给 MCP 工具的 file_base64 应该是纯 Base64，**不能带 data: 前缀**
  const pureBase64 = base64.split(',')[1];
  console.log("纯 Base64 长度:", pureBase64.length);
};
```

**判断**：
- ❌ 如果 `file_base64` 以 `data:` 开头 → **必须去掉前缀后再传**
- ❌ 如果 `pureBase64.length < 100` → Base64 内容太短，可能文件为空
- ❌ 如果 `pureBase64` 为空字符串 → 前端生成 Base64 失败

**修复**：确保传给 MCP 的 `file_base64` 是纯 Base64（不含 `data:` 前缀）。

```javascript
// 正确做法
const file_base64 = reader.result.split(',')[1];

// 错误做法（会把前缀也传过去）
const file_base64 = reader.result;  // ❌ 包含了 data:application/...;base64,
```

### 3. 检查是否同时发了多个请求导致覆盖

**操作**：打开浏览器 Network 面板，观察调用顺序

```
请求1: file_upload(file_base64=AAA, filename="个人简历空表.docx")     → 成功
请求2: smart_fill_form(file_base64=BBB, filename="个人简历空表.docx")  → 失败
```

**判断**：
- 如果 `AAA !== BBB`（两个请求的 Base64 不一致）→ **问题在这**：`file_upload` 上传了正确的文件 A，但 `smart_fill_form` 传了错误的文件 B，覆盖了文件 A
- 如果 `AAA === BBB`（一致）→ 问题可能出在后端或 MCP 服务器端

**修复**：确保传给 `file_upload` 和 `smart_fill_form` 的是**同一个 Base64**。

---

## 后端排查点

### 1. 检查后端调用 MCP 工具的参数

**操作**：在后端调用 MCP 工具的地方加日志

```python
# Python 后端示例
async def fill_form(file_base64, filename):
    print(f"[DEBUG] file_base64 长度: {len(file_base64)}")
    print(f"[DEBUG] file_base64 前50字符: {file_base64[:50]}")
    print(f"[DEBUG] filename: {filename}")

    result = await mcp_client.call_tool("smart_fill_form", {
        "file_base64": file_base64,
        "filename": filename,
        "knowledge_data": "..."
    })
    print(f"[DEBUG] MCP 返回: {result}")
    return result
```

**判断**：
- 如果 `len(file_base64) == 0` → 前端没传 Base64，或后端没正确接收
- 如果 `file_base64` 以 `data:` 开头 → 前端没去掉前缀，后端也没处理
- 如果 `len(file_base64)` 很小（比如 < 1000）→ 可能传了空文件或缩略图

### 2. 检查后端是否调用了 `file_upload` 和 `smart_fill_form`

如果后端流程是：
```
1. 调用 file_upload 上传文件 → 得到 server_path
2. 然后又调用 smart_fill_form（Base64 方式）→ 传了另一个 Base64
```

**这就是问题所在**。`smart_fill_form`（Base64 方式）会再次保存文件并覆盖 `file_upload` 的结果。

**修复**：
```python
# ❌ 错误做法：上传后再用 Base64 填表（重复上传 + 可能覆盖）
await mcp_client.call_tool("file_upload", {"content_base64": base64, "filename": name})
await mcp_client.call_tool("smart_fill_form", {"file_base64": base64, "filename": name})  # 会覆盖！

# ✅ 正确做法：上传后直接用本地路径填表
upload_result = await mcp_client.call_tool("file_upload", {"content_base64": base64, "filename": name})
server_path = upload_result["server_path"]
await mcp_client.call_tool("smart_fill_form_local", {
    "docx_path": server_path,
    "knowledge_data": knowledge_data
})
```

### 3. 检查后端 MCP Client 的错误处理

确保后端能看到完整的 MCP 错误返回：

```python
result = await mcp_client.call_tool("smart_fill_form", {...})
# 不要只取 result["status"]，要把完整 JSON 打印出来
print(json.dumps(result, ensure_ascii=False, indent=2))
```

---

## 推荐修复方案（一劳永逸）

### 方案 A：改后端调用链（推荐，改动最小）

把后端的填表调用从 `smart_fill_form`（Base64）改为 `smart_fill_form_local`（本地路径）。

**修改前**：
```python
# 后端：文件上传后，把 Base64 再传给 LLM，让 LLM 调 smart_fill_form
# 问题：Base64 太大、容易传错、有 15MB 限制
```

**修改后**：
```python
# 后端：文件上传后，直接把 server_path 注入 LLM 上下文
upload_result = await mcp_client.call_tool("file_upload", {
    "content_base64": base64_from_frontend,
    "filename": file.name
})
server_path = upload_result["server_path"]

# 把 server_path 和知识库结果一起给 LLM
llm_context = f"""
用户上传了空表，文件路径：{server_path}
知识库检索结果：{knowledge_data}
请调用 smart_fill_form_local 填表。
"""
response = await llm.chat(llm_context)
```

**优点**：
- 不消耗 LLM Token（不传 Base64）
- 无 15MB 文件限制
- 不会出现文件覆盖问题
- 前端不需要改代码

### 方案 B：前端校验 + 后端参数清洗

如果必须用 Base64 方式，在前端和后端都加校验：

**前端**：
```javascript
function validateFile(file) {
  if (!file.name.endsWith('.docx')) {
    alert('请上传 .docx 格式的文件（Word 2007 及以上版本）');
    return false;
  }
  if (file.size === 0) {
    alert('文件为空');
    return false;
  }
  return true;
}
```

**后端**：
```python
import base64

def clean_base64(raw_base64: str) -> str:
    """去掉 data: 前缀，返回纯 Base64"""
    if raw_base64.startswith("data:"):
        return raw_base64.split(",", 1)[1]
    return raw_base64

def validate_base64_size(b64_str: str) -> bool:
    """估算原始文件大小（Base64 长度 * 3/4）"""
    approx_bytes = len(b64_str) * 3 // 4
    return approx_bytes > 0  # 至少不是空文件
```

---

## 快速验证方法

让 opencode 在本地测试一下：

```bash
# 1. 确认文件是有效的 docx
python -c "import zipfile; print(zipfile.is_zipfile('个人简历空表.docx'))"
# 应该输出 True

# 2. 确认 Base64 能正确解码为有效 docx
python -c "
import base64, zipfile
with open('个人简历空表.docx', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
print('Base64 长度:', len(b64))
decoded = base64.b64decode(b64)
with open('/tmp/test.docx', 'wb') as f:
    f.write(decoded)
print('解码后是否有效 docx:', zipfile.is_zipfile('/tmp/test.docx'))
"
```

如果以上都通过，说明文件本身没问题，问题出在**平台传给 MCP 的 Base64 不正确**。
