FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mplconfig

# 安装系统依赖（gcc 用于编译；fonts-noto-cjk 保证图表中文正常显示）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 使用腾讯云镜像加速下载（清华源当前对部分包返回 403，与平台侧 Dockerfile 保持一致）
RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple/ \
    && pip config set global.timeout 300 \
    && pip config set global.retries 8

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据持久化目录 + 非 root 运行（沙箱与元数据库均需可写）
RUN useradd -m -u 10001 appuser \
    && mkdir -p /data/mcp-user-data /tmp/mplconfig \
    && chown -R appuser:appuser /app /data /tmp/mplconfig
USER appuser

# 数据持久化目录
VOLUME ["/data/mcp-user-data"]

EXPOSE 19104

CMD ["python", "server.py"]
