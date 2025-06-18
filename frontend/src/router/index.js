// frontend/src/router/index.js (完整代码)
import { createRouter, createWebHistory } from 'vue-router'
import ServerConfigView from '../views/ServerConfigView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/config'
    },
    {
      path: '/config',
      name: 'config',
      component: ServerConfigView
    },
    {
      path: '/media-download',
      name: 'media-download',
      component: () => import('../views/MediaDownloadView.vue')
    },
    {
      path: '/genre-mapper',
      name: 'genre-mapper',
      component: () => import('../views/GenreMapperView.vue')
    },
    {
      path: '/actor-localizer',
      name: 'actor-localizer',
      component: () => import('../views/ActorLocalizerView.vue')
    },
    {
      path: '/actor-gallery',
      name: 'actor-gallery',
      component: () => import('../views/ActorGalleryView.vue')
    },
    // --- 新增路由 ---
    {
      path: '/douban-fixer',
      name: 'douban-fixer',
      component: () => import('../views/DoubanFixerView.vue')
    },
    // --- 结束新增 ---
    {
      path: '/tasks',
      name: 'tasks',
      component: () => import('../views/TaskRunnerView.vue')
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('../views/LogView.vue')
    }
  ]
})

export default router