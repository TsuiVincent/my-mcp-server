FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（python-docx/openpyxl 等需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据持久化目录
VOLUME ["/data"]

EXPOSE 19100

CMD ["python", "server.py"]
