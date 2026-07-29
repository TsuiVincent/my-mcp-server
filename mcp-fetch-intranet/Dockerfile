FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 配置管理数据持久化
VOLUME ["/data/mcp-user-data"]

EXPOSE 8005

CMD ["python", "server.py"]
