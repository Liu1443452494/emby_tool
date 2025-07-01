# backend/Dockerfile (提供完整的修改后文件)

# 使用官方的 Python 3.11 slim 镜像作为基础
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 Python 写入 .pyc 文件
ENV PYTHONDONTWRITEBYTECODE 1
# 确保 Python 输出是无缓冲的，日志可以实时看到
ENV PYTHONUNBUFFERED 1

# --- 核心修改：安装 Node.js, ffmpeg, 以及 OpenCV 依赖 ---
# 更新包列表并安装所需工具
# - libgl1-mesa-glx 和 libglib2.0-0 是 opencv-python-headless 的运行时依赖
# -y 选项表示自动确认安装
# --no-install-recommends 减少不必要的包安装，保持镜像大小
# 最后清理 apt 缓存以减小镜像体积
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs \
    npm \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# 更新 pip 并使用清华大学镜像源安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制所有后端代码到容器中
COPY . .

# 暴露端口
EXPOSE 8000

# CMD 命令在 docker-compose.yml 文件中定义