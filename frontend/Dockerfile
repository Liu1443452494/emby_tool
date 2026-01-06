# frontend/Dockerfile (部分修改)
# ---- Stage 1: Build ----
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
# --- 修改行 ---
# 使用 npm ci 可以确保严格按照 lock 文件安装，并默认包含 devDependencies
# 这对于构建阶段是必需的
RUN npm ci --registry=https://registry.npmmirror.com
# --- 修改结束 ---
COPY . .
# 这里的 build 命令需要用到 devDependencies 里的 vite 和插件
RUN npm run build

# ---- Stage 2: Serve ----
FROM nginx:stable-alpine
# 核心：只从 build 阶段拷贝最终的产物 dist 目录
# node_modules 和所有 devDependencies 都被留在了 build 阶段，不会进入最终镜像
COPY --from=build /app/dist /usr/share/nginx/html

# 直接替换主配置文件
COPY nginx.conf /etc/nginx/nginx.conf

# 明确暴露我们正在使用的端口
EXPOSE 8270

CMD ["nginx", "-g", "daemon off;"]