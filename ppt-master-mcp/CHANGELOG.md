# PPT Master MCP 版本说明

## v2.0.0 (2026-07-29)

### 核心变更：同步 ppt-master-main v4.2.0

上游 ppt-master 项目重大升级（路由式架构、新扩展路线、DrawingML SVG 转换等），MCP 封装层同步跟进。

### 新增

- **统一源文档调度器**：`_tool_parse_source` 改用 `source_to_md.py` 统一入口，取代旧版按扩展名分派到 `pdf_to_md.py`/`doc_to_md.py`/`excel_to_md.py` 等子脚本的方式
- **新增工具**：`ppt_file_read_base64`（Base64 读取）、`ppt_get_template`（获取单个模板完整设计规范）
- **离线模式支持**：`.env` 新增 `PPT_AUDIO_ENABLED` 开关、3 组 TTS 后端配置、图片搜索 API Key 配置
- **Skill 文档升级**：路由式架构（Generate / Enhance / Fill / Create Template 四条路线）

### 依赖变更

| 新增 | 移除 |
|------|------|
| `skia-pathops>=0.9.2`（替换 Cairo） | `cairosvg` |
| `XlsxWriter>=3.0.0` | `cairocffi` |
| `numpy>=1.20.0` | `python-docx`（改用 mammoth） |
| `mammoth>=1.6.0` | `lxml` |
| `markdownify>=0.11.6` | `markdown` |
| `ebooklib>=0.18` | |
| `nbconvert>=7.0.0` | |
| `curl_cffi>=0.7.0` | |
| `google-genai>=1.0.0` | |
| `edge-tts>=7.2.8` | |
| `flask>=3.0.0` | |

### Docker 变更

- 新增系统依赖：`g++`、`pkg-config`（skia-pathops C++ 编译需要）
- 移除系统依赖：`libcairo2-dev`、`libpango1.0-dev`（不再需要 Cairo）
- 新增清华 pip 镜像加速

### 暂不暴露

- `ppt_native_enhance` 工具已编写代码但注释掉。Enhance Native PPTX 路由当前走现有工具组合（`workspace_init` → `parse_source` → `svg_to_pptx` → `export_pptx`），待 `native_enhance_pptx.py` 稳定后启用。

---

## v1.2.0 (2026-Q1)

### 核心功能

- 基于 ppt-master v4.x（线性流程）的 MCP 封装
- 12 个 MCP 工具：工作区管理、源文档解析、模板浏览、AI 生图、SVG→PPTX 转换、预览、导出
- 支持 PDF/DOCX/PPTX/XLSX/MD/URL 源文档解析
- 20+ 模板（Layouts/Decks/Charts）
- AI 生图支持（PPT_IMAGE_GEN_ENABLED 开关控制）

### 技术栈

- `python-pptx`、`cairosvg`、`PyMuPDF`、`python-docx`
- FastMCP（`mcp.server.fastmcp`）

---

## 升级指南

### 从 v1.2.0 升级到 v2.0.0

#### 前置条件

已从 GitHub 拉取最新 `ppt-master-main`（v4.2.0），覆盖本地 `ppt-master-mcp/ppt-master-main/` 目录。

#### 步骤

1. **同步依赖**：`requirements.txt` 已更新，移除 Cairo 系，新增 skia-pathops 等 11 个包

2. **重建 Docker 镜像**（无缓存）：
   ```powershell
   docker-compose build --no-cache ppt-master-mcp
   ```

3. **更新 .env**：复制新版 `.env.example`，根据环境选择是否开启新功能

4. **更新平台 Skill 文档**：使用新版 `ppt-master-skill.md`（路由式架构）

5. **验证**：
   ```powershell
   docker-compose up -d ppt-master-mcp
   docker-compose logs ppt-master-mcp
   ```

#### 回滚

如需回退到 v1.2.0：
```powershell
git checkout requirements.txt Dockerfile server.py .env.example
```

---

## 后续升级检查清单

每次同步上游 ppt-master 新版本时，对照以下项目检查：

| # | 检查项 | 涉及文件 |
|---|--------|---------|
| 1 | `skills/ppt-master/SKILL.md` → 路由架构是否变化 | `ppt-master-skill.md` |
| 2 | `skills/ppt-master/scripts/` → 新增脚本 | `requirements.txt`、`Dockerfile` |
| 3 | `skills/ppt-master/requirements.txt` → 新增/移除依赖 | `requirements.txt` |
| 4 | MCP `server.py` → `_run_python_script` 调用的脚本路径是否兼容 | `server.py` |
| 5 | Skill 文档 → 工具列表/工作流是否匹配实际 MCP 工具 | `ppt-master-skill.md` |
| 6 | `.env` 配置项 → 是否有新的功能开关/后端 | `.env`、`.env.example` |
| 7 | `platform_integration.py` → 工具种子数据是否同步 | `platform_integration.py` |
