# frontend/Dockerfile (完整文件覆盖)

# ---- Stage 1: Build ----
FROM node:18-alpine AS build
WORKDIR /app

# 复制 package.json 和 lock 文件
COPY package*.json ./

# --- 核心修改 ---
# 使用 npm install 来安装所有依赖（包括 devDependencies）
# 这比 npm ci 更具兼容性，能更好地处理 lock 文件可能存在的不一致问题
RUN npm install --registry=https://registry.npmmirror.com
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