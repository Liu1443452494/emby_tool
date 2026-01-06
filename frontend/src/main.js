// frontend/src/main.js (完整文件覆盖 - 最终正确版)
import { createApp } from 'vue'
import { createPinia } from 'pinia'

// --- 核心修改：手动导入指令式组件的样式 ---
// 这是 Element Plus 按需加载的官方推荐做法，
// 用于解决 ElMessage, ElMessageBox 等在 <script> 中使用时样式丢失的问题。
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/notification/style/css'
import 'element-plus/es/components/loading/style/css'
// --- 修改结束 ---

import '@/assets/css/custom-loading.css'
import 'vfonts/Lato.css' // Naive UI 推荐字体

import App from './App.vue'
import router from './router/index'

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')