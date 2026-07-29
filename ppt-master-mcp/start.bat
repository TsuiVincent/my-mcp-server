@echo off
chcp 65001 >nul
echo ============================================
echo   PPT Master MCP Server 启动脚本
echo ============================================
echo.

REM 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查并安装依赖
echo [1/3] 检查依赖...
pip show mcp >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在安装依赖包...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)
echo [完成] 依赖已就绪

REM 检查 .env 文件
echo [2/3] 检查配置...
if not exist .env (
    echo [提示] 未找到 .env 文件，使用默认配置
    copy .env.example .env >nul 2>&1
)

REM 启动服务器
echo [3/3] 启动 MCP Server...
echo.
echo MCP Server: http://localhost:8011/sse
echo 预览服务: 自动分配端口（从 18111 开始）
echo.
python server.py --port 8011 --transport sse

pause
