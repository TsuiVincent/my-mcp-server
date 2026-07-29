FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（psutil 等可能需要编译）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 升级 pip 并设置国内镜像源（可选，提高下载速度）
RUN pip install --no-cache-dir --upgrade pip && \
    pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 先复制 requirements.txt 并安装依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 暴露端口（根据实际情况调整）
EXPOSE 8004

# 运行服务
CMD ["python", "server.py"]