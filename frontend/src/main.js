// frontend/src/main.js (完整代码)

import { createApp } from 'vue'
import { createPinia } from 'pinia'

// 引入 Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '@/assets/css/custom-loading.css'
import App from './App.vue'
import router from './router/index'

const app = createApp(App)

app.use(createPinia())
app.use(router)

// 使用 Element Plus
app.use(ElementPlus)

app.mount('#app')