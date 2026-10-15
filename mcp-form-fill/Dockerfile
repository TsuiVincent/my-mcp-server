FROM python:3.11-slim
WORKDIR /app

# 安装中文字体（Word/Excel 填表保留格式需要）
# 密钥空窗期容错（2026-10-14 新存档签名密钥生效后可还原为普通 apt-get update）：
# trixie-updates/trixie-security 的 InRelease 在空窗期签名校验失败（sqv Not live），
# 中文字体包均在 main 源（签名正常），故 update 容错 + install 放行未认证包
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
    && (apt-get update -o Acquire::AllowInsecureRepositories=true || \
        echo '[build] 密钥空窗期：忽略 updates/security 仓库签名错误，中文字体均来自 main 源') \
    && apt-get install -y --no-install-recommends --allow-unauthenticated \
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
EXPOSE 19120
CMD ["python", "server.py"]
