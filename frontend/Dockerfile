# ---- Stage 1: Build ----
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

# ---- Stage 2: Serve ----
FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html

# 直接替换主配置文件
COPY nginx.conf /etc/nginx/nginx.conf

# --- 核心修改：移除行内注释 ---
# 明确暴露我们正在使用的端口
EXPOSE 8270

CMD ["nginx", "-g", "daemon off;"]