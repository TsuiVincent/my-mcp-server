# mcp-spreadsheet-pdf - Excel / CSV / PDF 操作 MCP Server

负责 Excel CRUD、CSV 结构化读写、PDF 提取/创建/合并/拆分。

## 启动

```bash
pip install -r requirements.txt
python server.py
```

默认监听 `http://0.0.0.0:8012`，使用 `streamable-http` 传输协议。

## 工具列表 (22个)

### Excel 操作 (12个)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `excel_create` | 创建新工作簿 | `filename`, `sheet_name`(可选) |
| `excel_read` | 读取工作表数据 | `path`, `sheet_name`(可选), `start_cell`, `end_cell`, `max_rows` |
| `excel_get_sheets` | 获取所有工作表信息 | `path` |
| `excel_write_cell` | 写入单元格（自动识别数字） | `path`, `cell`, `value`, `sheet_name`(可选) |
| `excel_write_row` | 写入一行数据 | `path`, `start_cell`, `values`(JSON数组) |
| `excel_write_data` | 批量写入结构化数据 | `path`, `data`(JSON), `start_cell`, `with_headers` |
| `excel_insert_rows` | 插入空行 | `path`, `row_index`, `count` |
| `excel_delete_rows` | 删除行 | `path`, `row_index`, `count` |
| `excel_merge_cells` | 合并单元格 | `path`, `cell_range`(如"A1:C1") |
| `excel_set_column_width` | 设置列宽 | `path`, `col_letter`, `width` |
| `excel_set_cell_style` | 设置字体/颜色/对齐/背景 | `path`, `cell_range`, `bold`, `font_size`, `font_color`, `bg_color`, `alignment` |
| `excel_add_sheet` | 添加工作表 | `path`, `sheet_name` |

### CSV 操作 (4个)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `csv_read` | 读取 CSV（自动检测分隔符） | `path`, `encoding`, `delimiter`(auto), `max_rows` |
| `csv_write` | 写入 CSV（支持追加） | `path`, `data`(JSON), `headers`, `delimiter`, `encoding`, `append` |
| `csv_analyze` | 分析列类型/空值/样本 | `path`, `encoding` |
| `csv_query` | 简单查询过滤 | 待实现 |

### PDF 操作 (6个)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `pdf_read_text` | 提取文本（pdfplumber 高精度） | `path`, `start_page`, `end_page`, `max_chars` |
| `pdf_get_info` | 获取元信息（页数/大小/加密等） | `path` |
| `pdf_merge` | 合并多个 PDF | `paths`(JSON数组), `output_filename` |
| `pdf_split` | 拆分 PDF（按范围或每N页） | `path`, `page_ranges` 或 `split_every` |
| `pdf_extract_page` | 提取单页为新 PDF | `path`, `page`, `output_filename`(可选) |
| `pdf_create` | 从文本生成 PDF | `text`, `output_filename`, `font_size`, `alignment`, `font_name` |

## 设计原则

- 所有工具返回 JSON 格式，`{"status":"ok", ...}` 或 `{"error":"..."}`
- 路径安全：仅允许沙箱目录和宿主机 Downloads/Desktop/Documents 映射
- Excel 大文件防护：`excel_read` 默认最多读取 500 行
- PDF 文本提取：优先使用 pdfplumber（精度高），PyPDF2 作回退
- CSV 自动识别：`csv_read` 默认自动检测分隔符，兼容 Excel 导出的 BOM CSV
