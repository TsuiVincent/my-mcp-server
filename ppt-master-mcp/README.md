# PPT Master MCP Server

AI 驱动的 PPT 生成服务。将 [ppt-master](https://github.com/hugohe3/ppt-master) 的 PPT 生成能力封装为 MCP (Model Context Protocol) 工具，支持通过 MCP 协议调用。

## 功能概览

| 工具 | 说明 |
|------|------|
| `ppt_workspace_init` | 初始化 PPT 项目工作区 |
| `ppt_file_write` | 写入工作区文件（SVG 页面等） |
| `ppt_file_read` | 读取工作区文件（回顾前页保持风格一致） |
| `ppt_file_list` | 列出工作区所有文件 |
| `ppt_parse_source` | 解析源文档（PDF/DOCX/PPTX/XLSX/MD/URL）为 Markdown |
| `ppt_list_templates` | 列出所有可用模板（brands/layouts/decks/charts），含设计规范 |
| `ppt_generate_image` | AI 图像生成配图（需配置 API Key，见下方） |
| `ppt_svg_to_pptx` | SVG 转为可编辑 PPTX（分页拆分 → SVG 最终化 → PPTX 组装） |
| `ppt_render_preview` | 生成预览 HTML 并启动预览服务器 |
| `ppt_export_pptx` | 获取已生成 PPTX（Base64 + HTTP 下载双通道） |
| `ppt_get_info` | 获取工作区状态信息 |
| `ppt_project_cleanup` | 清理项目工作区 |

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MCP_HOST` | 绑定地址 | `0.0.0.0` |
| `MCP_PORT` | 服务端口 | `8011` |
| `WORKSPACES_DIR` | 工作区目录 | `./workspaces` |
| `PPT_MASTER_PATH` | ppt-master 项目路径 | `./ppt-master-main` |
| `PPT_IMAGE_GEN_ENABLED` | AI 生图开关 | `false` |

---

## 本地开发运行

### 1. 安装依赖

```bash
cd ppt-master-mcp
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python server.py --port 8011
```

启动日志：
```
PPT Master MCP Server 启动中...
  - AI 图像生成: 已关闭（PPT_IMAGE_GEN_ENABLED=false）
使用 SSE 传输模式: http://0.0.0.0:8011/sse
```

### 3. 测试

在 MCP 客户端中连接 `http://127.0.0.1:8011/mcp`，调用 `ppt_list_templates` 验证。

---

## Docker 运行

### 前提

确保 `docker-compose.yml` 所在的项目根目录下有 `.env` 文件：

```bash
# 项目根目录 e:\Python_Project\work_plication\my-mcp-server\.env
PPT_IMAGE_GEN_ENABLED=true
```

### 启动

```bash
cd 项目根目录
docker-compose up -d ppt-master-mcp
```

### 停止

```bash
docker-compose stop ppt-master-mcp
```

### 查看日志

```bash
docker-compose logs -f ppt-master-mcp
```

### 重建镜像（代码改动后必须执行）

```bash
docker-compose up -d --build ppt-master-mcp
```

---

## 打开 / 关闭 AI 生图功能

AI 生图通过 `PPT_IMAGE_GEN_ENABLED` 环境变量控制，支持 **不重建镜像、一行改完重启**。

### 方式一：`.env` 控制（推荐，Docker 环境）

编辑项目根目录 `.env` 文件：

```env
# 开启生图
PPT_IMAGE_GEN_ENABLED=true

# 关闭生图
PPT_IMAGE_GEN_ENABLED=false
```

然后重启容器（**不重建**）：

```bash
docker-compose up -d ppt-master-mcp
```

`docker-compose.yml` 中已配置为自动读取：

```yaml
environment:
  - PPT_IMAGE_GEN_ENABLED=${PPT_IMAGE_GEN_ENABLED:-true}
```

`${PPT_IMAGE_GEN_ENABLED:-true}` 的含义：优先读 `.env` 文件的值，读不到则默认 `true`。

### 方式二：命令行覆盖（一次性，不修改文件）

```bash
# 开启
set PPT_IMAGE_GEN_ENABLED=true && docker-compose up -d ppt-master-mcp

# 关闭
set PPT_IMAGE_GEN_ENABLED=false && docker-compose up -d ppt-master-mcp
```

### 方式三：本地开发直接设环境变量

```bash
# Windows PowerShell
$env:PPT_IMAGE_GEN_ENABLED = "true"
python server.py --port 8011

# Linux / macOS
PPT_IMAGE_GEN_ENABLED=true python server.py --port 8011
```

### 验证开关状态

查看启动日志第一行：

```
AI 图像生成功能已启用        ← 开启成功
AI 图像生成功能已关闭（...）  ← 关闭状态
```

---

## 配置生图后端（开启后必需）

生图开关打开后，还需配置具体 AI 后端的 API Key。

### 1. 复制 `.env` 模板

```bash
cd ppt-master-mcp
cp ppt-master-main/.env.example ppt-master-main/.env
```

### 2. 选择后端并填写

编辑 `ppt-master-mcp/ppt-master-main/.env`：

**OpenAI（推荐，`gpt-image-2` 综合质量最佳）**

```env
IMAGE_BACKEND=openai
OPENAI_API_KEY=sk-你的APIKey
OPENAI_MODEL=gpt-image-2
```

**硅基流动（国内免翻，性价比高）**

```env
IMAGE_BACKEND=siliconflow
SILICONFLOW_API_KEY=sk-你的Key
SILICONFLOW_MODEL=Qwen/Qwen-Image
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1/images/generations
```

**通义 Qwen**

```env
IMAGE_BACKEND=qwen
QWEN_API_KEY=你的DashScopeKey
QWEN_MODEL=qwen-image-2.0-pro
```

**智谱 GLM**

```env
IMAGE_BACKEND=zhipu
ZHIPU_API_KEY=你的Key
ZHIPU_MODEL=glm-image
```

**火山引擎（豆包）**

```env
IMAGE_BACKEND=volcengine
VOLCENGINE_API_KEY=你的Key
VOLCENGINE_MODEL=doubao-seedream-4-5-251128
```

### 3. 重建并重启

```bash
docker-compose up -d --build ppt-master-mcp
```

### 验证

调用工具：

```
ppt_generate_image(project_id="xxx", prompt="A futuristic city skyline", backend="siliconflow")
```

返回 `base64_data` 即为成功。

---

## 完整流程示例

```
1. 配置 .env（生图开关 + API Key）
2. docker-compose up -d --build ppt-master-mcp
3. 确认日志: "AI 图像生成功能已启用"
4. MCP 客户端调用 ppt_workspace_init → ppt_parse_source → ... → ppt_export_pptx
5. PPTX 文件通过 file_save_to_download 保存到平台供下载
```

---

## 模板体系

PPT Master 内置 20+ 模板，分四类：

- **Brands（品牌配色规范）**：企业/机构品牌色板（中国电信、中汽研、中国电建、Google、Anthropic 等）
- **Layouts（布局风格）**：配色/字体/排版方案，含 20 种页面类型，适合快速出稿
- **Decks（品牌模板包）**：含品牌素材的完整模板（中国电信、中汽研等）
- **Charts（图表组件）**：76 个图表 SVG 模板（柱状图、饼图、甘特图、SWOT、思维导图等）

通过 `ppt_list_templates` 查看所有可用模板及其设计规范。

---

## 技术架构

```
MCP Client  →  ppt-master-mcp (server.py, 端口 8011)
                  ├── workspace 管理（项目创建/文件读写）
                  ├── 源文档解析（PDF/DOCX/PPTX/URL → Markdown）
                  ├── 模板浏览
                  ├── AI 生图（ppt-master-main/scripts/image_gen.py）
                  ├── SVG → PPTX 导出（ppt-master-main/scripts/svg_to_pptx/）
                  └── 预览服务（内置 HTTP snippet server）
```

核心依赖：`python-pptx`、`cairosvg`、`PyMuPDF`、`python-docx`、`markitdown`。

---

## 升级指南

当 [ppt-master 上游项目](https://github.com/hugohe3/ppt-master) 发布新版本时，按以下步骤升级。

### 升级步骤概览

1. **备份旧版本** → 2. **克隆新源码** → 3. **验证关键文件** → 4. **检查 server.py 兼容性** → 5. **对比依赖** → 6. **检查 Dockerfile** → 7. **更新 Skill 文档** → 8. **更新版本号** → 9. **更新平台集成** → 10. **测试验证**

### Step 1：备份 + 克隆

```powershell
cd ppt-master-mcp
Rename-Item ppt-master-main ppt-master-main.bak
git clone https://gitcode.com/hugohe3/ppt-master ppt-master-main
```

### Step 2：验证关键文件

确认以下文件/目录存在：
```
skills/ppt-master/SKILL.md                     # 路由架构入口
skills/ppt-master/workflows/routing.md          # 路由选择权威
skills/ppt-master/scripts/svg_to_pptx.py        # SVG→PPTX 主脚本
skills/ppt-master/scripts/source_to_md.py       # 源文档解析调度器
skills/ppt-master/scripts/total_md_split.py      # 演讲者笔记拆分
skills/ppt-master/scripts/finalize_svg.py       # SVG 最终化
skills/ppt-master/scripts/project_manager.py    # 项目管理
skills/ppt-master/templates/layouts/layouts_index.json
skills/ppt-master/templates/decks/decks_index.json
skills/ppt-master/templates/brands/brands_index.json
skills/ppt-master/templates/charts/charts_index.json
skills/ppt-master/requirements.txt              # 核心项目依赖
```

### Step 3：检查 server.py 兼容性

| 函数 | 检查项 |
|------|--------|
| `_tool_parse_source` | `source_to_md/` 子转换器路径 |
| `_tool_svg_to_pptx` | `svg_to_pptx.py` / `total_md_split.py` / `finalize_svg.py` 参数 |
| `_read_design_spec` | `design_spec.md` 路径（v4.2.0: `templates/` 子目录） |
| `_list_*_templates` | 模板索引 JSON 结构 |
| `_tool_get_template` | charts 索引结构 `{"meta":..., "charts":...}` |

### Step 4：对比依赖

```powershell
diff (Get-Content requirements.txt) (Get-Content ppt-master-main/requirements.txt)
```

确认 MCP 端缺失的依赖并补充。常见遗漏：`cairosvg`, `lxml`, `Pillow`, `cairocffi`。

### Step 5：检查 Docker 构建

```powershell
# 检查 Dockerfile 系统依赖
# 内网离线部署：先在联网环境预下载 wheels
pip download -r requirements.txt -d offline_wheels/
```

### Step 6：更新 Skill 和版本号

- 更新 `../ppt-master-skill.md`（工具列表、模板分类、工作流步骤）
- 更新 `VERSION`（核心版本、同步日期、MCP 版本）
- 更新 `platform_integration.py`（`version` 字段、`tools` 列表）

### Step 7：测试 + 清理

```powershell
python server.py --port 8011          # 启动测试
# 或仅检查语法: python -m py_compile server.py
Remove-Item -Recurse -Force ppt-master-main.bak
```

> 完整操作步骤详见 [VERSION](VERSION) 文件。

---

## 相关链接

- [ppt-master 上游项目](https://github.com/hugohe3/ppt-master)
- [项目内完整中文文档](ppt-master-main/README_CN.md)
- [常见问题](ppt-master-main/docs/zh/faq.md)
