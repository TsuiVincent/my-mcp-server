"""
MinerU 文档解析工具 - 通过远程 MinerU API 实现文档解析
"""
import os
import json
import tempfile
import httpx
from mcp.server.fastmcp import FastMCP


def _build_headers(api_key: str) -> dict:
    """构建请求头"""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _resolve_file(file_path: str = "", url: str = "") -> tuple[str, str, bool]:
    """
    解析文件来源：本地路径或 URL 下载。
    返回 (最终路径, 文件名, 是否需要清理临时文件)
    """
    if url:
        # 从 URL 下载到临时文件
        try:
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
        except httpx.ConnectError as e:
            raise RuntimeError(f"无法连接到文件下载地址 ({url}): {e}")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"下载文件失败 (HTTP {e.response.status_code}): {url}")
        except httpx.TimeoutException:
            raise RuntimeError(f"下载文件超时: {url}")

        # 从 URL 中推断文件名
        filename = url.rstrip("/").split("/")[-1] or "downloaded_file"
        # 写入临时文件
        suffix = os.path.splitext(filename)[1] or ""
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)
        return tmp_path, filename, True
    else:
        # 本地文件
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在 - {file_path}")
        return file_path, os.path.basename(file_path), False


def register_parse_tools(mcp: FastMCP, mineru_api_url: str = "http://localhost:8000", mineru_api_key: str = ""):
    """
    注册文档解析工具
    :param mineru_api_url: MinerU API 基础地址
    :param mineru_api_key: MinerU API 密钥（可选）
    """
    base_url = mineru_api_url.rstrip("/")
    headers = _build_headers(mineru_api_key)

    @mcp.tool()
    def parse_document(
        file_path: str = "",
        url: str = "",
        backend: str = "pipeline",
        ocr: bool = False,
        formula: bool = True,
        table: bool = True,
        language: str = "ch",
        pages: str = "",
    ) -> str:
        """
        将文档发送到远程 MinerU 服务进行解析，返回 Markdown 文本

        Args:
            file_path: 本地文档路径（PDF/DOCX/PPTX/XLSX/图片），与 url 二选一
            url: 远程文档 URL（HTTP 下载地址，用于 agent 平台传参），与 file_path 二选一
            backend: 解析后端，可选 pipeline / hybrid-engine / vlm-engine，默认 pipeline
            ocr: 是否启用 OCR（扫描件/图片 PDF 建议开启）
            formula: 是否启用公式识别（默认开启）
            table: 是否启用表格识别（默认开启）
            language: 文档语言，ch=中文, en=英文, jp=日语 等
            pages: 指定页码范围，如 "1-10" 或 "1,3,5"，空表示全部

        Returns:
            解析后的 Markdown 文本及结构化信息
        """
        if not file_path and not url:
            return "错误：请提供 file_path（本地路径）或 url（远程地址）"
        if url and file_path:
            return "错误：file_path 和 url 不能同时提供，请选择其中一种"

        # 解析文件来源
        try:
            resolved_path, filename, needs_cleanup = _resolve_file(file_path, url)
        except (FileNotFoundError, RuntimeError) as e:
            return str(e)

        f = None
        try:
            f = open(resolved_path, "rb")
            files = {"files": (filename, f)}

            data = {
                "backend": backend,
                "lang_list": language,
                "return_md": "true",
                "return_content_list": "true",
                "ocr_enabled": str(ocr).lower(),
                "formula_enabled": str(formula).lower(),
                "table_enabled": str(table).lower(),
            }
            if pages:
                data["pages"] = pages

            with httpx.Client(timeout=600) as client:
                resp = client.post(
                    f"{base_url}/file_parse",
                    files=files,
                    data=data,
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.ConnectError as e:
            return f"错误：无法连接到 MinerU 服务 ({base_url})，请检查服务是否已启动。详情: {e}"
        except httpx.TimeoutException:
            return "错误：MinerU 解析超时（>600秒），文件可能过大或服务繁忙"
        except httpx.HTTPStatusError as e:
            return f"错误：MinerU 服务返回异常 (HTTP {e.response.status_code}): {e.response.text}"
        except OSError as e:
            return f"错误：无法读取文件 - {e}"
        finally:
            if f:
                f.close()
            if needs_cleanup:
                os.unlink(resolved_path)

        try:
            result = resp.json()
        except json.JSONDecodeError:
            # 可能返回的是 ZIP 文件
            return f"解析完成，返回二进制数据包（{len(resp.content)} 字节），请使用 parse_document_async 获取结构化结果"

        # 提取并格式化输出
        output_parts = []

        # 优先返回 Markdown
        md = result.get("markdown", "")
        if md:
            output_parts.append(md)

        # 如果有 content_list，也附加
        content_list = result.get("content_list", [])
        if content_list:
            output_parts.append("\n--- 内容结构 ---\n" + json.dumps(content_list, ensure_ascii=False, indent=2))

        return "\n".join(output_parts) if output_parts else json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def parse_document_async(
        file_path: str = "",
        url: str = "",
        backend: str = "pipeline",
        ocr: bool = False,
        formula: bool = True,
        table: bool = True,
        language: str = "ch",
        pages: str = "",
    ) -> str:
        """
        异步提交文档解析任务，返回 task_id（适合大文件或批量处理）

        Args:
            file_path: 本地文档路径，与 url 二选一
            url: 远程文档 URL（HTTP 下载地址），与 file_path 二选一
            backend: 解析后端
            ocr: 是否启用 OCR
            formula: 是否启用公式识别
            table: 是否启用表格识别
            language: 文档语言
            pages: 指定页码范围

        Returns:
            task_id，可用于 get_task_status / get_task_result 查询
        """
        if not file_path and not url:
            return "错误：请提供 file_path（本地路径）或 url（远程地址）"
        if url and file_path:
            return "错误：file_path 和 url 不能同时提供，请选择其中一种"

        try:
            resolved_path, filename, needs_cleanup = _resolve_file(file_path, url)
        except (FileNotFoundError, RuntimeError) as e:
            return str(e)

        f = None
        try:
            f = open(resolved_path, "rb")
            files = {"files": (filename, f)}

            data = {
                "backend": backend,
                "lang_list": language,
                "return_md": "true",
                "return_content_list": "true",
                "ocr_enabled": str(ocr).lower(),
                "formula_enabled": str(formula).lower(),
                "table_enabled": str(table).lower(),
            }
            if pages:
                data["pages"] = pages

            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{base_url}/tasks",
                    files=files,
                    data=data,
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.ConnectError as e:
            return f"错误：无法连接到 MinerU 服务 ({base_url})。详情: {e}"
        except httpx.HTTPStatusError as e:
            return f"错误：提交任务失败 (HTTP {e.response.status_code}): {e.response.text}"
        except OSError as e:
            return f"错误：无法读取文件 - {e}"
        finally:
            if f:
                f.close()
            if needs_cleanup:
                os.unlink(resolved_path)

        result = resp.json()
        task_id = result.get("task_id", "")
        if task_id:
            return f"任务已提交，task_id: {task_id}\n请使用 get_task_status('{task_id}') 查询进度"
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def get_task_status(task_id: str) -> str:
        """
        查询异步解析任务的状态

        Args:
            task_id: 任务 ID（由 parse_document_async 返回）

        Returns:
            任务状态和进度信息
        """
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{base_url}/tasks/{task_id}",
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.ConnectError as e:
            return f"错误：无法连接到 MinerU 服务 ({base_url})。详情: {e}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"任务 {task_id} 不存在或已过期"
            return f"错误：查询任务失败 (HTTP {e.response.status_code})"

        result = resp.json()
        status = result.get("status", "unknown")
        progress = result.get("progress", 0)
        msg = f"任务状态: {status}"
        if progress:
            msg += f"，进度: {progress}%"
        if status == "completed":
            msg += "\n任务已完成，请使用 get_task_result 获取结果"
        elif status == "failed":
            error = result.get("error", "未知错误")
            msg += f"\n任务失败: {error}"
        return msg

    @mcp.tool()
    def get_task_result(task_id: str) -> str:
        """
        获取异步解析任务的最终结果

        Args:
            task_id: 任务 ID（由 parse_document_async 返回）

        Returns:
            解析后的 Markdown 文本
        """
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{base_url}/tasks/{task_id}/result",
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.ConnectError as e:
            return f"错误：无法连接到 MinerU 服务 ({base_url})。详情: {e}"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return f"任务 {task_id} 不存在或结果已过期"
            return f"错误：获取结果失败 (HTTP {e.response.status_code})"

        content_type = resp.headers.get("content-type", "")

        if "application/json" in content_type:
            result = resp.json()
            md = result.get("markdown", "")
            if md:
                return md
            return json.dumps(result, ensure_ascii=False, indent=2)
        elif "application/zip" in content_type or "application/octet-stream" in content_type:
            # 返回 ZIP 包，提示用户通过文件保存
            output_path = f"mineru_result_{task_id}.zip"
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return f"解析结果已保存为 {output_path}（{len(resp.content)} 字节）"
        else:
            return resp.text