import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 这是一个标准的 Vite + Vue 项目配置文件

export default defineConfig(({ command }) => {
  const isProduction = command === 'build';

  return {
    plugins: [
      vue(),
      // 核心修改：移除 vite-plugin-vue-devtools，因为它不应该在生产环境中使用，
      // 并且我们没有在 package.json 中将其作为生产依赖。
      // 如果您在本地开发时需要它，请通过 `npm install -D vite-plugin-vue-devtools` 安装，
      // 并在这里有条件地加载它，例如：
      // !isProduction && vueDevTools(),
    ],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      }
    },
    // 为生产构建添加配置
    build: {
      outDir: 'dist', // 输出目录
      assetsDir: 'assets', // 静态资源目录
      sourcemap: false, // 生产环境不生成 sourcemap
    },
    // 为开发服务器添加配置 (如果需要)
    server: {
      port: 5173, // 这是 Vite dev server 的默认端口
      proxy: {
        // 在开发环境中，我们可以使用 Vite 的代理来解决跨域问题，
        // 这样就不需要修改 apiConfig.js 来回切换了。
        // 但我们之前的方案（Nginx代理）更适合生产环境，所以这里保持注释。
        // '/api': {
        //   target: 'http://127.0.0.1:8000',
        //   changeOrigin: true,
        // },
        // '/ws': {
        //   target: 'ws://127.0.0.1:8000',
        //   ws: true,
        // },
      }
    }
  }
})