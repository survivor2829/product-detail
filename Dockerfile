FROM python:3.11-slim

# 国内 apt 源（腾讯云）
RUN sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.cloud.tencent.com|g' /etc/apt/sources.list 2>/dev/null; true

# 系统依赖（Playwright Chromium 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-cjk \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 国内 pip 源（腾讯云）
RUN pip config set global.index-url https://mirrors.cloud.tencent.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.cloud.tencent.com

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn requests

# Playwright Chromium（从官方CDN下载）
RUN playwright install chromium

# 复制项目文件
COPY . .

# 创建运行时目录
RUN mkdir -p static/uploads static/outputs output instance

# 环境变量
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# 用 gunicorn 生产级启动（Render 用 $PORT 环境变量，本地默认 5000）
# workers 默认2，支持多用户并发；可通过 WORKERS 环境变量调整
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} --workers ${WORKERS:-2} --timeout 180 app:app
