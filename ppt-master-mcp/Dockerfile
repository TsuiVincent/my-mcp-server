FROM python:3.11-slim

WORKDIR /app

# ============================================================
# 系统依赖
# ============================================================
# gcc/g++ — skia-pathops 需要 C++ 编译
# libcairo2-dev / libpango1.0-dev — cairosvg 需要
# ffmpeg (可选) — audio 模块计算音频时长
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libcairo2-dev \
    libpango1.0-dev \
    libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Python 依赖
# ============================================================
# 当前：联网环境直接安装
# 内网离线部署时，先在联网环境执行:
#   pip download -r requirements.txt -d ./offline_wheels/
# 然后替换下面两行为离线安装模式
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================
# 应用代码
# ============================================================
COPY . .

# ============================================================
# 运行时配置
# ============================================================
VOLUME ["/app/workspaces"]

EXPOSE 8011

# 离线模式环境变量（内网部署时设置）
# PPT_OFFLINE_MODE=true  → 关闭所有外网依赖功能
# PPT_IMAGE_GEN_ENABLED=false → 关闭 AI 图像生成
# PPT_AUDIO_ENABLED=false → 关闭旁白音频合成
ENV PPT_OFFLINE_MODE=true
ENV PPT_IMAGE_GEN_ENABLED=false
ENV PPT_AUDIO_ENABLED=false

CMD ["python", "server.py", "--port", "8011"]
