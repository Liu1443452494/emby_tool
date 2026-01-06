// frontend/src/main.js (部分修改)
import { createApp } from 'vue'
import { createPinia } from 'pinia'

import '@/assets/css/custom-loading.css'
import App from './App.vue'
import router from './router/index'

const app = createApp(App)

app.use(createPinia())
app.use(router)



app.mount('#app')