FROM python:3.11-slim

WORKDIR /app

# WITH_RENDER=1 时安装 Playwright + Chromium（镜像约 +1GB），支持 JS 渲染抓取
ARG WITH_RENDER=0
ENV WITH_RENDER=${WITH_RENDER}

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN if [ "$WITH_RENDER" = "1" ]; then \
        pip install --no-cache-dir "playwright>=1.40,<2" && \
        playwright install --with-deps chromium; \
    fi

COPY . .

# 配置管理数据持久化
VOLUME ["/data/mcp-user-data"]

EXPOSE 19107

CMD ["python", "server.py"]
