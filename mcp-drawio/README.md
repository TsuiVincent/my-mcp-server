# mcp-drawio - Draw.io 图表生成与预览 MCP Server

基于 draw.io 的 AI 图表生成服务。LLM 生成 draw.io XML，通过本服务在浏览器中实时预览，支持导出多种格式。

> 灵感来源：[next-ai-draw-io](https://github.com/DayuanJiang/next-ai-draw-io)

## 启动

```bash
pip install -r requirements.txt
python server.py
```

- MCP 端口: `19110`（streamable-http 协议）
- 预览端口: `19111`（HTTP，自动找空闲端口）
- draw.io 嵌入源: `https://embed.diagrams.net`（可通过 `DRAWIO_BASE_URL` 配置）

## 工具列表 (7个)

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `drawio_start_session` | 创建绘图会话，返回预览 URL | 无 |
| `drawio_get_diagram` | 获取当前图表 XML | `session_id` |
| `drawio_create_diagram` | 创建或替换图表（完整 XML） | `session_id`, `xml` |
| `drawio_edit_diagram` | 编辑图表 cell（增/删/改） | `session_id`, `operation`, `cell_id`, `attributes` |
| `drawio_export_diagram` | 导出图表为文件 | `session_id`, `output_filename`, `format` |
| `drawio_add_page` | 追加新页面 | `session_id`, `page_name` |
| `drawio_list_pages` | 列出所有页面 | `session_id` |
| `drawio_list_formats` | 查看 draw.io XML 格式参考 | 无 |

## 使用流程

```
1. LLM 调用 drawio_start_session → 获得 session_id + preview_url
2. 用户打开 preview_url 在浏览器中实时预览
3. LLM 调用 drawio_list_formats 了解 XML 格式
4. LLM 生成 draw.io mxfile XML，调用 drawio_create_diagram
5. 浏览器自动刷新显示图表
6. LLM 可调用 drawio_edit_diagram 微调（增删改 cell）
7. LLM 调用 drawio_export_diagram 导出为 .drawio / .png / .svg
```

## Draw.io XML 格式速览

### 基本结构

```xml
<mxfile host="app.diagrams.net">
  <diagram name="Page-1" id="page1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- 你的 cell 放这里 -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

### 形状 (vertex)

```xml
<mxCell id="2" value="Hello" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="120" height="60" as="geometry"/>
</mxCell>
```

### 连线 (edge)

```xml
<mxCell id="3" style="endArrow=classic;html=1;" edge="1" parent="1" source="2" target="4">
  <mxGeometry relative="1" as="geometry"/>
</mxCell>
```

### 常用样式

| 形状 | style 值 |
|------|----------|
| 矩形 | `rounded=0;whiteSpace=wrap;html=1;` |
| 圆角矩形 | `rounded=1;whiteSpace=wrap;html=1;` |
| 椭圆 | `ellipse;whiteSpace=wrap;html=1;` |
| 菱形 | `rhombus;whiteSpace=wrap;html=1;` |
| 圆柱 | `shape=cylinder3;whiteSpace=wrap;html=1;` |
| 文本 | `text;html=1;align=center;` |

### 颜色样式追加

```
style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontColor=#333333;"
```

## 导出格式

| 格式 | 说明 |
|------|------|
| `drawio` | .drawio 文件，可用桌面版/VS Code 插件打开 |
| `png` | PNG 图片（2x 缩放） |
| `svg` | SVG 矢量图 |

## 平台配置

### Cherry Studio / Cursor / Claude Desktop

```json
{
  "mcpServers": {
    "mcp-drawio": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:19110/mcp"
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DRAWIO_BASE_URL` | `https://embed.diagrams.net` | draw.io 嵌入源，可指向自部署实例 |
| `DRAWIO_PREVIEW_PORT` | 自动分配 | 预览 HTTP 服务固定端口 |
| `DRAWIO_PREVIEW_BASE` | `http://127.0.0.1:{port}` | 预览服务对外 URL（Docker 时需要配置） |

### 自部署 draw.io（私有化场景）

```bash
docker run -d -p 8080:8080 jgraph/drawio
```

然后设置 `DRAWIO_BASE_URL=http://localhost:8080`。

## Docker 部署

```yaml
# docker-compose.yml
mcp-drawio:
  build: ./mcp-drawio
  container_name: mcp-drawio
  restart: unless-stopped
  ports:
    - "19110:19110"
    - "19111:19111"
  environment:
    - DRAWIO_PREVIEW_BASE=http://<服务器IP>:19111
  volumes:
    - drawio_data:/data/drawio
```

## 依赖

```
mcp>=1.6.0
httpx>=0.27.0
uvicorn>=0.30.0
starlette>=0.38.0
python-dotenv
```
