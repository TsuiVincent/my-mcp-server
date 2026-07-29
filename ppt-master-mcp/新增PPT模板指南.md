# 新增 PPT 模板指南

ppt-master-mcp 支持三类模板：**Layouts（布局风格）**、**Decks（品牌模板包）**、**Charts（图表模板）**。新增后用户通过 `ppt_list_templates` 即可发现和使用。

---

## 目录结构总览

```
ppt-master-mcp/
└── ppt-master-main/
    └── skills/ppt-master/templates/
        ├── layouts/              ← 布局风格模板
        │   ├── layouts_index.json   ← 模板索引（新增后必须更新）
        │   ├── ai_ops/              ← 示例：一个 layout 模板目录
        │   │   ├── 01_cover.svg
        │   │   ├── 02_toc.svg
        │   │   ├── 02_chapter.svg
        │   │   ├── 03_content.svg
        │   │   ├── 04_ending.svg
        │   │   └── design_spec.md   ← 设计规范（AI生成SVG的参考依据）
        │   ├── government_blue/
        │   └── ... (更多)
        ├── decks/                ← 品牌整包模板
        │   ├── decks_index.json     ← 模板索引
        │   ├── 招商银行/             ← 示例：一个 deck 模板目录
        │   │   ├── 01_cover.svg
        │   │   ├── 02_toc.svg
        │   │   ├── 02_chapter.svg
        │   │   ├── 03_content.svg
        │   │   ├── 04_ending.svg
        │   │   ├── design_spec.md
        │   │   ├── logo_dark.png     ← 品牌素材
        │   │   └── cover_bg.png
        │   └── ... (更多)
        └── charts/               ← 图表组件模板（71个，一般不需新增）
            ├── charts_index.json
            └── *.svg
```

---

## 方式一：新增 Layout 布局模板（推荐，最常见）

Layout 是纯设计风格的页面布局，**不含品牌元素**，用户可按主题选择后由 AI 生成对应风格的 SVG。

### 步骤 1：准备 SVG 页面文件

在 `templates/layouts/` 下新建目录，放入 5-6 个标准 SVG 文件：

| 文件 | 用途 | 说明 |
|------|------|------|
| `01_cover.svg` | 封面页 | 标题、副标题、日期、作者等占位信息 |
| `02_toc.svg` | 目录页 | 章节列表占位 |
| `02_chapter.svg` | 章节过渡页 | 章节标题、编号 |
| `03_content.svg` | 正文内容页 | 正文区域、图表占位、要点列表 |
| `04_ending.svg` | 结束页 | 致谢、联系方式 |

SVG 要求：
- 画布尺寸：**1280 × 720 px**（16:9），viewBox="0 0 1280 720"
- 使用**纯文本/占位符**而非真实内容（AI 生成时会替换）
- 建议用 `<text>` 元素标记可替换区域，如 `<text>标题占位</text>`
- 参考已有模板目录中的 SVG 文件格式

### 步骤 2：编写 design_spec.md 设计规范

这是 AI 生成该风格 SVG 时的**核心参考文档**。参考 `layouts/ai_ops/design_spec.md`，应包含：

```markdown
---
layout_id: my_template        # 目录名
kind: layout
summary: 适用场景简述（英文，1-2句）
canvas_format: ppt169
page_count: 5
page_types: [cover, toc, chapter, content, ending]
---

# 模板名称 - 设计规范

## I. 模板概述
- 模板名称、适用场景、设计基调
- 主题模式（浅色/深色）
- 信息密度

## II. 画布规范
- 尺寸：1280 × 720 px
- 页边距、内容安全区域
- 标题区域位置

## III. 核心设计原则
- 配色方案（主色、辅助色、背景色，含色值）
- 字体规范（标题字体、正文字体、字号层级）
- 布局风格（左栏右栏/上下/居中）
- 视觉元素规则（装饰线、色块、图标风格）

## IV. 页面结构
- 每种页面类型（cover/toc/chapter/content/ending）的详细区域划分

## V. 禁止事项
- 明确列出生成时不能使用的元素和做法
```

### 步骤 3：更新 layouts_index.json

在 `templates/layouts/layouts_index.json` 中新增一条记录：

```json
"my_template": {
  "summary": "适用场景简述：产品发布、商业计划、营销方案.",
  "canvas_format": "ppt169",
  "page_count": 5,
  "page_types": ["cover", "toc", "chapter", "content", "ending"]
}
```

**字段说明**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `summary` | 是 | 适用场景描述，AI 用于匹配用户需求（中英均可） |
| `canvas_format` | 是 | 固定 `ppt169`（16:9） |
| `page_count` | 是 | 提供的 SVG 页面数量 |
| `page_types` | 是 | 页面类型列表，决定 AI 可使用的页面种类 |
| `primary_color` | 否 | 主色值，如 `"#C00000"`，可选 |

### 步骤 4：验证

完成以上三步后，无需重启服务器（`ppt_list_templates` 实时读取），LLM 调用即可发现新模板。

---

## 方式二：新增 Deck 品牌整包模板

Deck 是带有品牌元素的完整模板包（Logo、品牌色、背景图等），适合企业定制。

### 步骤 1：准备素材

在 `templates/decks/` 下新建目录，放入：

| 文件 | 用途 |
|------|------|
| `01_cover.svg` ~ `04_ending.svg` | 各页面 SVG（含品牌元素） |
| `design_spec.md` | 设计规范（格式同 Layout） |
| `logo.png` | 品牌 Logo |
| 其他图片 | 背景图、装饰元素等 |

### 步骤 2：更新 decks_index.json

```json
"我的企业_商务": {
  "summary": "企业汇报、商务提案、产品发布、客户演示.",
  "canvas_format": "ppt169",
  "page_count": 5,
  "primary_color": "#003399"
}
```

### 步骤 3：SVG 中的品牌素材引用

SVG 中使用**相对路径**引用同目录下的图片：

```xml
<image href="logo.png" x="50" y="30" width="120" height="40"/>
```

---

## 方式三：新增 Charts 图表模板（高级，一般不需）

图表模板是独立的 SVG 组件，用于嵌入正文页。新增需：

1. 在 `templates/charts/` 下放置 `.svg` 文件
2. 在 `charts_index.json` 的 `charts` 字段中新增记录：

```json
"my_chart": {
  "summary": "Pick for <适用场景>. Skip if <不适用场景>."
}
```

> chart `summary` 格式固定，必须遵循"Pick for ... Skip if ..."语法，用于 AI 自动选图。

---

## 模板设计最佳实践

### 1. 配色方案建议

| 场景 | 主色 | 辅助色 |
|------|------|--------|
| 政务/党建 | `#C00000` / `#1A3C6D` | 金色 `#D4A853` |
| 科技/互联网 | `#2E75B6` / `#00A0E9` | 深灰 `#333333` |
| 医疗/学术 | `#006BB7` / `#009B77` | 浅蓝 `#E8F4FD` |
| 金融/商务 | `#003366` / `#C8152D` | 暖灰 `#F5F5F5` |

### 2. 字体兼容性

SVG 中使用 `font-family="PingFang SC, Microsoft YaHei, sans-serif"` 确保跨平台兼容。

### 3. 一页 vs 五页

- **Layout 模板**必须提供 5-6 页（cover → toc → chapter → content → ending）
- **Deck 模板**至少提供 cover + content + ending 三页
- 每种页面类型**只提供一个 SVG**，AI 会基于 design_spec 变体生成更多页

### 4. 图片素材的使用方法

模板目录中可以放置图片素材（Logo、背景图、装饰图等），SVG 通过 `<image>` 标签引用。这在 **Deck 品牌模板**中尤其常用，Layout 模板也可以使用。

#### 支持的图片格式

| 格式 | 支持情况 | 推荐用途 |
|------|---------|---------|
| PNG | 完全支持 | Logo、透明背景装饰 |
| JPG/JPEG | 完全支持 | 背景图、照片 |
| SVG | 支持（作为 `<image>` 嵌入） | 矢量装饰、图标 |
| GIF | 不支持 | 不要使用 |

#### SVG 中引用图片素材

将图片文件放在模板目录内，SVG 中使用**相对路径**引用：

```xml
<!-- 引用同目录下的 Logo -->
<image href="logo.png" x="80" y="40" width="120" height="48"/>

<!-- 引用同目录下的背景图 -->
<image href="cover_bg.png" x="0" y="0" width="1280" height="720"
       preserveAspectRatio="xMidYMid slice"/>

<!-- 先画背景色垫底，再用半透明图片叠加 -->
<rect width="1280" height="720" fill="#8F0F1B"/>
<image href="cover_bg.png" x="0" y="0" width="1280" height="720"
       preserveAspectRatio="xMidYMid slice"/>
<rect width="1280" height="720" fill="#8F0F1B" fill-opacity="0.18"/>
```

> 参考：`decks/招商银行/01_cover.svg` 使用了 `cover_bg.png` 作为封面底纹。

#### `preserveAspectRatio` 属性说明

| 值 | 效果 | 适用场景 |
|----|------|---------|
| `xMidYMid meet` | 等比缩放，完整显示，可能有留白 | Logo |
| `xMidYMid slice` | 等比缩放，填满区域，可能裁切 | 全屏背景图 |
| `none` | 拉伸填满，不保持比例 | 不推荐 |

#### 图片素材如何到达 PPTX

Pipeline 会自动处理图片引用：

```bash
# finalize_svg.py 的 align-images 步骤会：
# 1. 读取磁盘上的原始图片文件
# 2. 根据 preserveAspectRatio 调整位置和尺寸
# 3. 将图片 Base64 内联嵌入 SVG
# 4. svg_to_pptx.py 再将其转为 PPTX 内嵌图片
python3 scripts/finalize_svg.py <project_path>
python3 scripts/svg_to_pptx.py <project_path>
```

**不需要手动做任何处理**，只需确保图片文件和 SVG 在同一目录即可。

#### Layout 模板（AI 生成）使用图片的注意事项

Layout 模板的 SVG 会被 AI 读取并生成新内容。如果 SVG 中引用了图片素材：

- **AI 可以看到图片引用**（`<image href="xxx.png"/>`），但无法访问图片内容
- 应在 `design_spec.md` 的**禁止事项**中明确说明："图片元素 `<image href="..."/>` 不得修改或删除，保持原始位置和尺寸"
- 如果希望 AI 理解图片的作用，在 `design_spec.md` 中描述图片内容

```markdown
## 内置素材说明

| 文件 | 用途 | AI 生成时 |
|------|------|----------|
| `logo.png` | 单位 Logo（左上角 80,40） | **不得修改、删除或移动** |
| `cover_bg.png` | 封面底纹（全幅 1280×720） | **不得修改、删除或移动** |
| `decoration.png` | 页脚装饰条 | **不得修改、删除或移动** |
```

#### 常见问题

**Q: 图片为什么在预览时显示但在导出的 PPTX 中消失？**

A: 检查 `finalize_svg.py` 是否运行。图片必须经过 `align-images` 步骤 Base64 嵌入才能被 `svg_to_pptx` 识别。

**Q: 图片在 PPTX 中被拉伸变形？**

A: 给 `<image>` 添加正确的 `preserveAspectRatio` 属性。默认的 `xMidYMid meet` 在某些 PowerPoint 版本中会被忽略，建议显式设置。

**Q: PNG 透明区域在 PPTX 中变成黑色？**

A: PowerPoint 对 PNG 透明度支持不稳定。建议给 `<image>` 下方放一个同色 `<rect>` 垫底，避免依赖 PNG 透明通道。

---

## 新增后效果

用户对话中：

```
用户：帮我做一份商业计划PPT
AI：请选择模板风格 —— 共 N 个可用：
   Layouts: ai_ops（科技运维）、government_blue（政务蓝）、my_template（我的新模板）...
   Decks: 招商银行、中国电信...
```

LLM 调用 `ppt_list_templates` 即可自动列出新模板，`design_spec.md` 内容也会一并返回供 AI 参考生成。
