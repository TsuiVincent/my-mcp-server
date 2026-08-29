FROM python:3.11-slim
WORKDIR /app

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
        fonts-arphic-uming \
        fonts-arphic-ukai && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt
COPY . .
RUN mkdir -p /usr/share/fonts/truetype/custom && \
    cp /app/方正小标宋简.TTF /usr/share/fonts/truetype/custom/ 2>/dev/null; \
    fc-cache -fv
EXPOSE 19121
CMD ["python", "server.py"]
