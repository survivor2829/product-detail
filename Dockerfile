# 显式 pin bookworm：trixie 于 2025 年转稳后 `python:3.11-slim` 自动切 trixie,
# 引发 libicu72→libicu76 + t64 过渡（libasound2→libasound2t64 等 15+ 包改名）
FROM python:3.11-slim-bookworm

# 腾讯云 apt 镜像：Bookworm DEB822 格式 + 旧格式双路径替换（容错）
RUN sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list 2>/dev/null; true

# 显式列出 Chromium 运行时依赖，不依赖 `playwright install --with-deps` 自动检测
# （Bookworm DEB822 下自动检测会漏包，腾讯云部署已失败过 3 次）
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libgbm1 \
    libglib2.0-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxshmfence1 \
    libgdk-pixbuf-2.0-0 \
    libgtk-3-0 \
    libharfbuzz0b \
    libicu72 \
    libjpeg62-turbo \
    libpng16-16 \
    libwebp7 \
    libwoff1 \
    libxml2 \
    libxslt1.1 \
    libfontconfig1 \
    libfreetype6 \
    libenchant-2-2 \
    libsecret-1-0 \
    libhyphen0 \
    libmanette-0.2-0 \
    libflite1 \
    libgles2 \
    libegl1 \
    libgudev-1.0-0 \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    libgstreamer-plugins-bad1.0-0 \
    libgstreamer-gl1.0-0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    libevdev2 \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.cloud.tencent.com

# 系统依赖已在上一步装好，这里只拉浏览器二进制
RUN pip install --no-cache-dir playwright && \
    playwright install chromium

# requirements.txt 单独 COPY：只有它变化才重装 Python 依赖（利用 Docker 层缓存）
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn requests

# 预下载 rembg 模型（ghfast.top 镜像）：避免运行时首次抠图超时；失败则运行时兜底
RUN mkdir -p /root/.u2net && \
    wget -q --timeout=30 --tries=2 \
      -O /root/.u2net/isnet-general-use.onnx \
      "https://ghfast.top/https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx" \
    || echo "[WARN] rembg 模型下载失败，运行时首次抠图会自动下载"

COPY . .

# -rf 而非 -f:本地 instance/ 会被 COPY . . 带进镜像(可能是目录也可能是软链),rm -f 只能删文件会挂
RUN rm -rf instance && mkdir -p static/uploads static/outputs output instance

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# gunicorn 生产启动，WORKERS/PORT 可通过环境变量覆盖
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} --workers ${WORKERS:-2} --timeout 180 app:app
