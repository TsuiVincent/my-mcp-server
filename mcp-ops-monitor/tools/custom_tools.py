import asyncio
import subprocess
import json
from mcp.server.fastmcp import FastMCP


def register_custom_tools(mcp: FastMCP):

    @mcp.tool()
    async def run_command(command: str, cwd: str = None, timeout: int = 30) -> str:
        """执行服务器命令行"""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return json.dumps({
                "code": proc.returncode,
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace')
            }, ensure_ascii=False)
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def get_system_info() -> str:
        """获取服务器系统信息"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "uname", "-a",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            return stdout.decode('utf-8', errors='replace')
        except Exception:
            import platform
            return json.dumps({
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine()
            }, ensure_ascii=False)
