FROM python:3.11-slim
WORKDIR /app

# 安装中文字体（PDF 生成需要）
# fonts-wqy-zenhei  →  黑体/宋体 兜底
# fonts-arphic-uming →  仿宋
# fonts-arphic-ukai  →  楷体
# fonts-wqy-microhei →  微软雅黑
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
        fonts-arphic-uming \
        fonts-arphic-ukai && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 安装自定义中文字体（方正小标宋简体等）
RUN mkdir -p /usr/share/fonts/truetype/custom && \
    cp /app/方正小标宋简.TTF /usr/share/fonts/truetype/custom/ 2>/dev/null; \
    fc-cache -fv
EXPOSE 19109
CMD ["python", "server.py"]
