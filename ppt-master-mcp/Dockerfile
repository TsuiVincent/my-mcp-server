FROM python:3.11-slim

WORKDIR /app

# 系统依赖（skia-pathops 需要 C++ 编译，PyMuPDF 需要额外库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 清华镜像加速（内网部署时改为内网 PyPI 镜像地址）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 工作区数据持久化
VOLUME ["/app/workspaces"]

EXPOSE 8011

CMD ["python", "server.py", "--port", "8011"]
