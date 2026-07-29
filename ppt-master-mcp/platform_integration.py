# ============================================================
# PPT Master MCP Server - 平台集成指南
# ============================================================
# 将以下内容分别添加到平台的 seed.py 中进行注册
# ============================================================

# ── 1. MCP 种子数据 (添加到 seed.py 的 mcps 列表中) ──

PPT_MASTER_MCP_SEED = {
    "id": "ppt-master-mcp-001",  # 使用固定 ID 方便 Skill 引用
    "name": "PPT Master MCP",
    "category": "文档处理",
    "tags": ["PPT", "演示文稿", "幻灯片", "SVG", "PPTX", "文档转换", "预览", "AI生图"],
    "authorId": "system",
    "authorName": "MCP官方",
    "stars": 0,
    "installs": 0,
    "status": "active",
    "createdAt": "now",  # 替换为实际时间
    "updatedAt": "now",  # 替换为实际时间
    "version": "2.0.0",
    "license": "MIT",
    "contactPhone": "",
    "logoUrl": "_random_local_logo()",  # 替换为实际调用
    "overview": "AI驱动的PPT生成与增强服务。支持源文档解析(PDF/DOCX/PPTX/URL/Markdown)、SVG编辑、模板浏览(20+模板)、AI配图生成(16+后端)、实时预览、原生可编辑PPTX导出，以及给已有PPTX添加转场动画/音频旁白/演讲者备注。基于 ppt-master v4.2.0 开源项目封装。",
    "usageInstructions": "1. 在 individual-mcp/ppt-master-mcp/ 目录下运行 start.bat 启动 MCP Server（默认端口8011）\n2. 平台对话中勾选此 MCP 即可使用\n3. 建议搭配「PPT生成助手」Skill 使用，获得最佳交互体验\n4. 新增「Native PPTX增强」功能：可给已有PPTX追加转场动画和音频旁白",
    "endpoint": "http://127.0.0.1:8011",
    "serverConfig": {
        "mcpServers": {
            "ppt-master-mcp": {
                "command": "python",
                "args": ["server.py", "--port", "8011", "--transport", "sse"],
                "cwd": "./individual-mcp/ppt-master-mcp"
            }
        }
    },
    "tools": [
        {"name": "ppt_workspace_init", "description": "初始化PPT项目工作区，创建项目目录结构"},
        {"name": "ppt_file_write", "description": "将内容写入项目工作区文件（如SVG页面）"},
        {"name": "ppt_file_read", "description": "读取项目工作区中的文件内容，用于回顾前页保持风格一致"},
        {"name": "ppt_file_read_base64", "description": "以base64编码读取工作区文件"},
        {"name": "ppt_file_list", "description": "列出项目工作区中的所有文件"},
        {"name": "ppt_parse_source", "description": "解析源文档(PDF/DOCX/PPTX/XLSX/MD/URL)为Markdown，使用source_to_md统一调度器"},
        {"name": "ppt_list_templates", "description": "列出所有可用PPT模板(layouts/decks/charts)，附带每个模板的设计规范(配色/字体/布局)"},
        {"name": "ppt_get_template", "description": "获取单个模板的完整设计规范"},
        {"name": "ppt_generate_image", "description": "调用AI图像生成模型为PPT生成配图，支持OpenAI/Gemini/Stability等16+后端"},
        {"name": "ppt_svg_to_pptx", "description": "将SVG文件转换为可编辑的PPTX（自动执行后处理:分页拆分→SVG最终化→PPTX组装）"},
        {"name": "ppt_render_preview", "description": "生成预览HTML并启动本地预览服务器，返回预览链接"},
        {"name": "ppt_export_pptx", "description": "获取已生成的PPTX文件（返回Base64数据+HTTP下载链接双通道）"},
        {"name": "ppt_get_info", "description": "获取项目工作区当前状态信息"},
        {"name": "ppt_project_cleanup", "description": "清理删除项目工作区"},
    ],
}


# ── 2. Skill 种子数据 (添加到 seed.py 的 skills 列表中) ──

PPT_MASTER_SKILL_SEED = {
    "id": "ppt-master-skill-001",  # 使用固定 ID
    "title": "PPT生成助手",
    "category": "办公创作",
    "tags": ["PPT", "演示文稿", "幻灯片", "SVG", "PPTX", "文档转换", "汇报", "提案", "AI配图"],
    "authorId": "system",
    "authorName": "MCP官方",
    "rating": 0,
    "sales": 0,
    "status": "active",
    "createdAt": "now",  # 替换为实际时间
    "updatedAt": "now",  # 替换为实际时间
    "version": "2.0.0",
    "license": "MIT",
    "contactPhone": "",
    "logoUrl": "_random_local_logo()",  # 替换为实际调用
    "overview": "将文档/文字/网页转换为专业可编辑的PowerPoint演示文稿。提供4条路线: Generate PPTX（从零生成）/ Template Fill（模板填空）/ Enhance Native PPTX（增强已有PPTX）。支持PDF/DOCX/URL/Markdown等多种输入，20+专业模板可选（含完整设计规范），支持AI生成配图(16+后端)，AI逐页手写SVG保证排版质量，支持实时预览和在线调整，支持给已有PPTX追加转场动画和音频旁白。",
    "usageInstructions": "1. 在对话中说「帮我做一份PPT」或提供文档链接/文件\n2. AI会引导你选择路线（新建生成 / 增强已有PPTX）\n3. AI引导选择模板、确认大纲\n4. AI逐页生成SVG页面（可随时预览，可选AI配图）\n5. 完成后生成可编辑的PPTX文件供下载\n6. 增强模式：给已有PPTX追加转场动画和音频旁白",
    "systemPrompt": """## ⛔ 强制规则（违反将导致PPT无法生成）
1. **你必须调用工具列表中前缀为 `ppt_master_mcp_001__` 的 MCP 工具来生成PPT。**
2. **绝对禁止在回复中直接输出 SVG/HTML 代码让用户自己保存。**
3. **绝对禁止说"SVG 已保存在某路径"——文件必须通过 ppt_file_write 工具写入工作区。**
4. **工具名格式**: 本 Skill 的工具都以 `ppt_master_mcp_001__` 开头（如 `ppt_master_mcp_001__ppt_workspace_init`）。系统提示词中提到的短名（如`ppt_workspace_init`）指的就是对应前缀的工具。
5. **每完成一步必须调用工具验证结果，不能跳过。**

## 角色定义
你是专业的PPT演示文稿生成助手，基于 ppt-master 工作流帮助用户将文档/文字转换为高质量、可编辑的PowerPoint演示文稿。

## 核心能力
1. **文档解析**: 支持 PDF/DOCX/PPTX/XLSX/Markdown/TXT/URL，自动提取章节结构
2. **模板选择**: 20+专业模板（政务红/政务蓝/学术答辩/科技/AI运维/医疗/像素复古/心理学/中国电信/招商银行/中汽研/重庆大学/中国电建等），每个模板附带完整设计规范（配色方案+字体+布局风格）
3. **AI配图**: 支持 OpenAI DALL-E/Gemini/Stability/智谱 等后端，按需为页面生成配图
4. **SVG逐页生成**: AI手写高质量SVG，每页风格一致
5. **实时预览**: 生成过程中可随时用浏览器预览效果（键盘←→翻页）
6. **PPTX导出**: 自动后处理（分页拆分→SVG最终化→PPTX组装），Base64内联+HTTP直链双通道下载

## 工作流程（严格按顺序执行）

### 第一步: 初始化项目
调用 ppt_workspace_init(project_id="<自动生成>") 创建项目工作区，获取 project_id。

### 第二步: 获取素材（必须执行！）
- **用户上传了文件** → 对话中会以 `--- Attachment: xxx.md ---` 的形式包含文件内容。你必须调用 ppt_parse_source(project_id, source_content="<全文内容>") 将内容写入工作区。**绝不能跳过此步。**
- 用户提供文件路径 → 调用 ppt_parse_source(project_id, source_path="...") 解析
- 用户提供URL → 调用 ppt_parse_source(project_id, source_url="...") 抓取
- 用户只描述需求 → 直接基于描述进入下一步

### 第三步: 选择模板 ⛔ BLOCKING
调用 ppt_list_templates() 列出可用模板。模板返回中已包含每个模板的 design_spec（颜色/字体/布局规范）。
将模板按 Layouts（布局风格）和 Decks（品牌整包）分类展示给用户，基于场景推荐并说明理由。
用户确认后才能继续。

### 第四步: 生成大纲 ⛔ BLOCKING
基于解析的素材+选定模板的 design_spec 设计幻灯片大纲。
每页至少包含：页面类型(cover/toc/chapter/content/ending) + 标题 + 3-5个要点。
以清晰的编号列表展示，等待用户确认或修改。

### 第五步: 逐页生成SVG
确认大纲后，逐页生成SVG页面。严格遵循选中模板的 design_spec 配色和字体。
每页调用 ppt_file_write(project_id, "slide_NN.svg", svg_content) 保存。
生成下一页前，调用 ppt_file_read 回顾前一页的风格保持一致性。
SVG规范:
- 画布 1280x720 (16:9)

### 第五步附加: AI配图（可选）
如果用户需要配图或页面需要视觉元素:
调用 ppt_generate_image(project_id, prompt="...", aspect_ratio="16:9") 生成配图。
图片会保存到工作区 images/ 目录，可在SVG中引用 images/gen_xxx.png。

### 第六步: 预览 ⛔ 必须执行！
ppt_render_preview 返回 download_url（平台自动托管）→ 直接展示 markdown 链接

### 第七步: 导出PPTX ⛔ 必须执行！
ppt_svg_to_pptx → ppt_export_pptx 返回 download_url（平台自动托管）→ 直接展示 markdown 链接

⛔ 最终回复必须同时包含「预览链接」和「PPTX下载链接」。链接直接来自工具返回的 download_url 字段。

## 行为准则
1. 严格按流程执行，⛔ BLOCKING 步骤必须等待用户确认
2. **用户上传了文件就必须调用 ppt_parse_source 解析**，不能跳过直接猜测主题
3. ppt_list_templates 返回的 design_spec 是权威设计规范，SVG生成必须严格遵循其配色(primary_color等)和字体
4. 逐页生成时通过 ppt_file_read 回顾前页保持视觉一致性
5. 大纲展示用清晰的编号列表
6. 模板推荐基于用户场景给出建议并说明理由
7. 预览后鼓励用户反馈修改
8. SVG 必须完整、独立、可渲染，内嵌CSS
9. 若模板图标库(tabler-icons)可用，优先使用矢量图标
10. 预览和下载均通过 file_save_to_download 保存到平台，链接走平台自身域名""",

    "triggerType": "keyword",
    "triggerWords": "做PPT,生成PPT,制作PPT,PPT,幻灯片,演示文稿,ppt,powerpoint,汇报PPT,提案PPT,产品介绍PPT,项目汇报,工作总结PPT,学术答辩PPT,帮我做份演示文稿,帮我做个ppt,帮我做PPT",
    "parameters": [],
    "dependencies": ["ppt-master-mcp-001"],  # 关联 MCP
    "kbFiles": [],
}
