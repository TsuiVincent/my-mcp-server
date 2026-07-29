# mcp-browser-playwright - 浏览器自动化 MCP Server

基于 Playwright 的内网浏览器自动化工具。支持页面导航、元素交互、截图、JS 执行等功能。

## 启动

```bash
pip install -r requirements.txt
playwright install chromium
python server.py
```

默认监听 `http://0.0.0.0:8008`，使用 `streamable-http` 传输协议。

## 工具列表 (14个)

### 页面导航
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `browser_navigate` | 导航到URL | `url` |
| `browser_snapshot` | 获取页面无障碍快照（结构化元素树） | 无 |
| `browser_screenshot` | 页面截图（Base64） | `full_page`(可选) |
| `browser_go_back` | 后退 | 无 |
| `browser_go_forward` | 前进 | 无 |

### 元素交互
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `browser_click` | 点击元素 | `ref`(snapshot引用) 或 `selector` |
| `browser_type` | 输入文本 | `ref`/`selector`, `text` |
| `browser_fill` | 填充表单 | `ref`/`selector`, `value` |
| `browser_select_option` | 选择下拉选项 | `ref`/`selector`, `value` |
| `browser_hover` | 悬停元素 | `ref`/`selector` |
| `browser_press_key` | 按键 | `key`(如 Enter/Tab/Escape) |

### 高级操作
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `browser_evaluate` | 执行JavaScript | `expression` |
| `browser_get_page_text` | 获取页面纯文本 | 无 |
| `browser_close` | 关闭页面/浏览器 | 无 |

## 使用场景

- 内网后台自动化操作（填单、查询、报表导出）
- 页面截图监控
- 网页数据抓取（配合 Snapshot 结构化提取）
- 前端回归测试

## 依赖

```
mcp>=1.6.0, httpx>=0.27.0, uvicorn>=0.30.0, playwright>=1.40.0
```

### Docker 部署注意

Docker 需要安装 Chromium 依赖库：

```dockerfile
RUN pip install playwright && playwright install chromium --with-deps
```
