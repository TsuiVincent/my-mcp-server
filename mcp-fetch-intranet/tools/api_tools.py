import httpx
import json
from mcp.server.fastmcp import FastMCP


def register_api_tools(mcp: FastMCP):
    """
    注册内网 API 调用工具
    按需修改下面的 endpoint 和参数
    """

    @mcp.tool()
    async def api_get(endpoint: str, params: str = "{}") -> str:
        """
        调用内网 GET API
        :param endpoint: 完整 URL，如 http://192.168.1.50:8080/api/users
        :param params: JSON 字符串，如 {"id": "123"}
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(endpoint, params=json.loads(params))
                return json.dumps({
                    "status": resp.status_code,
                    "body": resp.text
                }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def api_post(endpoint: str, data: str = "{}", headers: str = "{}") -> str:
        """
        调用内网 POST API
        :param endpoint: 完整 URL
        :param data: JSON 字符串请求体
        :param headers: JSON 字符串请求头
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    endpoint,
                    json=json.loads(data),
                    headers=json.loads(headers)
                )
                return json.dumps({
                    "status": resp.status_code,
                    "body": resp.text
                }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    # ========== 示例：封装特定内网系统 ==========
    @mcp.tool()
    async def query_erp_user(user_id: str) -> str:
        """查询内网 ERP 系统用户信息（示例）"""
        endpoint = f"http://192.168.1.50:8080/erp/api/users/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(endpoint)
                return resp.text
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def create_ticket(title: str, content: str, priority: str = "normal") -> str:
        """向内网工单系统创建工单（示例）"""
        endpoint = "http://192.168.1.60:9000/ticket/api/create"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(endpoint, json={
                    "title": title,
                    "content": content,
                    "priority": priority
                })
                return json.dumps({
                    "status": resp.status_code,
                    "ticket_id": resp.json().get("id") if resp.status_code == 200 else None
                }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"
