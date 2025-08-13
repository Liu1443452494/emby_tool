# backend/Dockerfile (最终修复版)

# 使用官方的 Python 3.11 slim 镜像作为基础
FROM python:3.11-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# --- 核心修改：安装 Node.js, ffmpeg, OpenCV 依赖, 以及 curl ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl && \
    rm -rf /var/lib/apt/lists/*

# 更新 pip 并安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制所有后端代码到容器中
COPY . .

# 暴露端口
EXPOSE 8000

# CMD 命令在 docker-compose.yml 文件中定义