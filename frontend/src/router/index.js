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
    {
      path: '/douban-fixer',
      name: 'douban-fixer',
      component: () => import('../views/DoubanFixerView.vue')
    },
    {
      path: '/poster-manager',
      name: 'poster-manager',
      component: () => import('../views/PosterManagerView.vue')
    },
    {
      path: '/actor-role-mapper',
      name: 'actor-role-mapper',
      component: () => import('../views/ActorRoleMapperView.vue')
    },
    {
      path: '/actor-avatar-mapper',
      name: 'actor-avatar-mapper',
      component: () => import('../views/ActorAvatarMapperView.vue')
    },
    {
      path: '/chasing-center',
      name: 'chasing-center',
      component: () => import('../views/ChasingCenterView.vue')
    },
    {
      path: '/upcoming-media',
      name: 'upcoming-media',
      component: () => import('../views/UpcomingMediaView.vue')
    },
    {
      path: '/episode-renamer',
      name: 'episode-renamer',
      component: () => import('../views/EpisodeRenamerView.vue')
    },
    {
      path: '/media-tagger',
      name: 'media-tagger',
      component: () => import('../views/MediaTaggerView.vue')
    },
    {
      path: '/scheduled-tasks',
      name: 'scheduled-tasks',
      component: () => import('../views/ScheduledTasksView.vue')
    },
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