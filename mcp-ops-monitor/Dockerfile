FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（psutil 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 需要访问宿主机 /proc 等系统文件才能监控
EXPOSE 8004

CMD ["python", "server.py"]
