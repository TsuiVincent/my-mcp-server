"""
MinerU 健康检查工具 - 检测远程 MinerU 服务的连通性
"""
import httpx
from mcp.server.fastmcp import FastMCP


def _build_headers(api_key: str) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def register_health_tools(mcp: FastMCP, mineru_api_url: str = "http://localhost:8000", mineru_api_key: str = ""):
    """
    注册健康检查工具
    :param mineru_api_url: MinerU API 基础地址
    :param mineru_api_key: MinerU API 密钥（可选）
    """
    base_url = mineru_api_url.rstrip("/")
    headers = _build_headers(mineru_api_key)

    @mcp.tool()
    def ping() -> str:
        """
        检测远程 MinerU 服务是否可达，返回服务状态信息

        Returns:
            MinerU 服务的健康状态
        """
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{base_url}/health", headers=headers)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        status = data.get("status", "ok")
                        return f"MinerU 服务状态: {status}\n地址: {base_url}\n响应: {data}"
                    except Exception:
                        return f"MinerU 服务已连接\n地址: {base_url}\nHTTP 状态: {resp.status_code}"
                else:
                    return f"MinerU 服务异常 (HTTP {resp.status_code})\n地址: {base_url}"
        except httpx.ConnectError:
            return f"无法连接到 MinerU 服务\n地址: {base_url}\n请检查服务是否已启动，或 MINERU_API_URL 配置是否正确"
        except httpx.TimeoutException:
            return f"连接 MinerU 服务超时\n地址: {base_url}"