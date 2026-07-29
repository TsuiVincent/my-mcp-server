# import httpx
# import json
# from mcp.server.fastmcp import FastMCP
# import os
# from dotenv import load_dotenv
# from pathlib import Path
# env_path = Path(__file__).parent / ".env"
# load_dotenv(dotenv_path=env_path)
#
# #该文档是个示例，整个功能未有真正进行注册。
# def register_api_tools(mcp: FastMCP):
#     """
#     注册内网 API 调用工具
#     按需修改下面的 endpoint 和参数
#     """
# 
#     @mcp.tool()
#     async def api_get(endpoint: str, params: str = "{}") -> str:
#         """
#         调用内网 GET API
#         :param endpoint: 完整 URL，如 http://192.168.1.50:8080/api/users
#         :param params: JSON 字符串，如 {"id": "123"}
#         """
#         try:
#             async with httpx.AsyncClient(timeout=30) as client:
#                 resp = await client.get(endpoint, params=json.loads(params))
#                 return json.dumps({
#                     "status": resp.status_code,
#                     "body": resp.text
#                 }, ensure_ascii=False)
#         except Exception as e:
#             return f"Error: {str(e)}"
#
#     @mcp.tool()
#     async def api_post(endpoint: str, data: str = "{}", headers: str = "{}") -> str:
#         """
#         调用内网 POST API
#         :param endpoint: 完整 URL
#         :param data: JSON 字符串请求体
#         :param headers: JSON 字符串请求头
#         """
#         try:
#             async with httpx.AsyncClient(timeout=30) as client:
#                 resp = await client.post(
#                     endpoint,
#                     json=json.loads(data),
#                     headers=json.loads(headers)
#                 )
#                 return json.dumps({
#                     "status": resp.status_code,
#                     "body": resp.text
#                 }, ensure_ascii=False)
#         except Exception as e:
#             return f"Error: {str(e)}"
#
#     # ========== 示例：封装特定内网系统 ==========
#     @mcp.tool()
#     async def query_erp_user(user_id: str) -> str:
#         """查询内网 ERP 系统用户信息（示例）"""
#         endpoint = f"http://192.168.1.50:8080/erp/api/users/{user_id}"
#         try:
#             async with httpx.AsyncClient(timeout=30) as client:
#                 resp = await client.get(endpoint)
#                 return resp.text
#         except Exception as e:
#             return f"Error: {str(e)}"
#
#     @mcp.tool()
#     async def create_ticket(title: str, content: str, priority: str = "normal") -> str:
#         """向内网工单系统创建工单（示例）"""
#         endpoint = "http://192.168.1.60:9000/ticket/api/create"
#         try:
#             async with httpx.AsyncClient(timeout=30) as client:
#                 resp = await client.post(endpoint, json={
#                     "title": title,
#                     "content": content,
#                     "priority": priority
#                 })
#                 return json.dumps({
#                     "status": resp.status_code,
#                     "ticket_id": resp.json().get("id") if resp.status_code == 200 else None
#                 }, ensure_ascii=False)
#         except Exception as e:
#             return f"Error: {str(e)}"
#
#     # ==========基于_markitdown REST API 封装的 FastMCP Server==========
#     Mkdown_API_BASE = os.getenv("markitdown_API_BASE")
#
#     @mcp.tool()
#     async def convert_url_to_markdown(url: str) -> str:
#         """将网页或在线文档 URL 转换为 Markdown 格式。
#
#         支持 HTTP/HTTPS 网页、YouTube 视频、Wikipedia 页面等。
#
#         Args:
#             url: 要转换的文档 URL，必须以 http:// 或 https:// 开头
#
#         Returns:
#             转换后的 Markdown 文本
#         """
#         async with httpx.AsyncClient(timeout=120) as client:
#             resp = await client.post(f"{Mkdown_API_BASE}/convert/url", json={"url": url})
#             data = resp.json()
#             if resp.status_code != 200:
#                 return f"转换失败: {data.get('error', '未知错误')}"
#             return data["markdown"]
#
#     @mcp.tool()
#     async def convert_text_to_markdown(text: str, extension: str = ".txt") -> str:
#         """将文本内容转换为 Markdown 格式。
#
#         可用于将 HTML、JSON 等文本内容转为 Markdown。
#
#         Args:
#             text: 要转换的文本内容
#             extension: 文件类型提示，如 .html、.json、.md，默认 .txt
#
#         Returns:
#             转换后的 Markdown 文本
#         """
#         async with httpx.AsyncClient(timeout=120) as client:
#             resp = await client.post(f"{Mkdown_API_BASE}/convert/text", json={
#                 "text": text,
#                 "extension": extension,
#             })
#             data = resp.json()
#             if resp.status_code != 200:
#                 return f"转换失败: {data.get('error', '未知错误')}"
#             return data["markdown"]
#
#     @mcp.tool()
#     async def convert_file_to_markdown(file_path: str) -> str:
#         """将本地文件转换为 Markdown 格式。
#
#         支持的格式: pdf, docx, pptx, xlsx, xls, html, txt, md, json, csv, epub, zip, ipynb, jpg, png, wav, mp3, msg 等。
#
#         Args:
#             file_path: 本地文件的绝对路径
#
#         Returns:
#             转换后的 Markdown 文本
#         """
#         from pathlib import Path
#
#         path = Path(file_path)
#         if not path.exists():
#             return f"文件不存在: {file_path}"
#
#         async with httpx.AsyncClient(timeout=120) as client:
#             with open(path, "rb") as f:
#                 resp = await client.post(
#                     f"{Mkdown_API_BASE}/convert/file",
#                     files={"file": (path.name, f)},
#                     data={"return_content": "true"},
#                 )
#             data = resp.json()
#             if resp.status_code != 200:
#                 return f"转换失败: {data.get('error', '未知错误')}"
#             return data["markdown"]
#
#     @mcp.tool()
#     async def get_supported_formats() -> str:
#         """查询 MarkItDown 支持的文件格式列表。
#
#         Returns:
#             按类别分组的支持格式列表
#         """
#         async with httpx.AsyncClient(timeout=30) as client:
#             resp = await client.get(f"{Mkdown_API_BASE}/formats")
#             data = resp.json()
#
#             result = "MarkItDown 支持的文件格式:\n\n"
#             for category, formats in data["categories"].items():
#                 result += f"- {category}: {', '.join('.' + f for f in formats)}\n"
#             return result
#
#
