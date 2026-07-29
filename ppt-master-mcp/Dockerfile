FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（cairosvg 需要 cairo/pango, PyMuPDF 需要额外库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libcairo2-dev \
    libpango1.0-dev \
    libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 工作区数据持久化
VOLUME ["/app/workspaces"]

EXPOSE 8011

CMD ["python", "server.py", "--port", "8011"]
