// frontend/src/App.vue (完整代码)

<template>
  <el-config-provider :locale="locale">
    <el-container class="app-layout">
      <!-- 左侧边栏 -->
      <el-aside :width="isCollapse ? '80px' : '240px'" class="sidebar">
        <div class="sidebar-header" :class="{ 'is-collapsed': isCollapse }">
          <h1 v-if="!isCollapse">Emby 媒体工具</h1>
          <h1 v-else>ET</h1>
          <div class="collapse-button" @click="isCollapse = !isCollapse">
            <el-icon>
              <ArrowLeft v-if="!isCollapse" />
              <ArrowRight v-else />
            </el-icon>
          </div>
        </div>
        
        <el-menu
          :default-active="activeMenu"
          class="sidebar-menu"
          :router="true"
          :collapse="isCollapse"
        >
          <el-menu-item index="/config">
            <el-icon><Setting /></el-icon>
            <template #title>Emby配置</template>
          </el-menu-item>
          
          <div class="menu-divider"></div>

          <el-menu-item index="/media-download">
            <el-icon><Film /></el-icon>
            <template #title>Emby媒体下载</template>
          </el-menu-item>
          
          <el-menu-item index="/genre-mapper">
            <el-icon><PriceTag /></el-icon>
            <template #title>类型替换</template>
          </el-menu-item>

          <el-menu-item index="/actor-localizer">
            <el-icon><User /></el-icon>
            <template #title>演员中文化</template>
          </el-menu-item>

          <el-menu-item index="/actor-gallery">
            <el-icon><Avatar /></el-icon>
            <template #title>媒体画廊</template>
          </el-menu-item>
          <el-menu-item index="/poster-manager">
            <el-icon><Picture /></el-icon>
            <template #title>海报管理器</template>
          </el-menu-item>
          <el-menu-item index="/actor-role-mapper">
            <el-icon><UserFilled /></el-icon>
            <template #title>演员角色映射</template>
          </el-menu-item>

          <!-- --- 新增菜单项 --- -->
          <el-menu-item index="/douban-fixer">
            <el-icon><MagicStick /></el-icon>
            <template #title>豆瓣ID修复器</template>
          </el-menu-item>
          <!-- --- 结束新增 --- -->
           <el-menu-item index="/episode-renamer">
            <el-icon><EditPen /></el-icon>
            <template #title>网盘文件重命名</template>
          </el-menu-item>

          <el-menu-item index="/scheduled-tasks">
            <el-icon><Clock /></el-icon>
            <template #title>定时任务</template>
          </el-menu-item>
          <!-- --- 结束新增 --- -->

          <div class="menu-divider"></div>

          <el-menu-item index="/tasks">
            <el-icon><DataLine /></el-icon>
            <template #title>运行任务</template>
          </el-menu-item>

          <el-menu-item index="/logs">
            <el-icon><Document /></el-icon>
            <template #title>应用日志</template>
          </el-menu-item>
        </el-menu>

      </el-aside>

      <!-- 右侧主内容区 -->
      <el-main class="content-panel">
        <div class="main-toolbar">
          <el-button 
            @click="toggleDark()" 
            :icon="isDark ? Moon : Sunny" 
            circle 
            title="切换主题"
          />
        </div>
        
        <RouterView />
      </el-main>
    </el-container>
  </el-config-provider>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { ElConfigProvider, ElIcon } from 'element-plus'
// --- 新增图标 ---
import { Setting, Film, PriceTag, User, Document, ArrowLeft, ArrowRight, DataLine, Avatar, Moon, Sunny, MagicStick,Clock, EditPen, Picture, UserFilled } from '@element-plus/icons-vue'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { useStorage } from '@vueuse/core'
import { useConfigStore } from '@/stores/config'

const locale = ref(zhCn)
const isCollapse = useStorage('main-sidebar-collapsed', false)

const isDark = ref(localStorage.getItem('theme') === 'dark')

const applyTheme = (isDarkValue) => {
  if (isDarkValue) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

const toggleDark = () => {
  isDark.value = !isDark.value
  applyTheme(isDark.value)
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}

const configStore = useConfigStore()

onMounted(() => {
  applyTheme(isDark.value)
  configStore.fetchConfig()
})


const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style>
@import "element-plus/theme-chalk/dark/css-vars.css";

:root {
  --menu-active-bg-color: #609e95;
  --menu-active-text-color: #ffffff;
  --el-font-size-base: 14px;
  --custom-bg-rgb: 242, 243, 245;
  --custom-bg-overlay-rgb: 255, 255, 255;
}

html.dark {
  --custom-dark-bg-base: #292A2D;
  --custom-dark-bg-overlay: #313235;
  --custom-dark-border-light: #48494d;
  --custom-dark-border-lighter: #3a3b3d;
  --custom-dark-border-extra-light: #313235;
  --custom-dark-text-primary: #e8eaed;
  --custom-dark-text-regular: #bdc1c6;
  --custom-dark-text-secondary: #969ba1;
  --custom-dark-text-placeholder: #7f8389;
  --custom-bg-rgb: 41, 42, 45;
  --custom-bg-overlay-rgb: 49, 50, 53;
  --el-bg-color-page: var(--custom-dark-bg-base);
  --el-bg-color: var(--custom-dark-bg-base);
  --el-bg-color-overlay: var(--custom-dark-bg-overlay);
  --el-border-color: var(--custom-dark-border-light);
  --el-border-color-light: var(--custom-dark-border-light);
  --el-border-color-lighter: var(--custom-dark-border-lighter);
  --el-border-color-extra-light: var(--custom-dark-border-extra-light);
  --el-fill-color: var(--custom-dark-bg-overlay);
  --el-fill-color-light: #48494d;
  --el-fill-color-lighter: #3a3b3d;
  --el-text-color-primary: var(--custom-dark-text-primary);
  --el-text-color-regular: var(--custom-dark-text-regular);
  --el-text-color-secondary: var(--custom-dark-text-secondary);
  --el-text-color-placeholder: var(--custom-dark-text-placeholder);
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  background-color: var(--el-bg-color-page);
}

.app-layout {
  height: 100vh;
}

.sidebar {
  position: relative;
  transition: width 0.3s;
  border-right: none; 
  background-color: var(--el-bg-color);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  height: 60px;
  line-height: 60px;
  text-align: center;
  flex-shrink: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  transition: all 0.3s;
  overflow: hidden;
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
}
.sidebar-header h1 {
  margin: 0;
  font-size: 1.4rem;
  color: var(--el-text-color-primary);
  white-space: nowrap;
}
.sidebar-header.is-collapsed h1 {
  font-size: 1.6rem;
}

.sidebar-menu {
  border-right: none !important;
  background-color: transparent !important;
  flex-grow: 1;
  padding-top: 10px;
}

.el-menu--collapse {
  width: 100%;
}

.el-menu-item {
  margin: 0 10px 8px 10px !important;
  height: 48px !important;
  line-height: 48px !important;
  border-radius: 8px !important;
}

.el-menu--collapse .el-menu-item .el-tooltip__trigger {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 0;
  width: 100%;
}

.el-menu-item .el-icon {
  font-size: 1.2rem;
  vertical-align: middle;
}

.el-menu-item.is-active {
  background-color: var(--menu-active-bg-color) !important;
  color: var(--menu-active-text-color) !important;
}

.el-menu-item.is-active .el-icon {
  color: var(--menu-active-text-color) !important;
}

.el-menu-item:hover {
  background-color: var(--el-color-info-light-8);
}
.dark .el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.08);
}

.menu-divider {
  margin: 10px 20px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.el-menu--collapse .menu-divider {
  display: none;
}

.collapse-button {
  position: absolute;
  top: 15px;
  right: -10px;
  transform: none;
  z-index: 10;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  background-color: transparent;
  border: none;
  color: var(--el-text-color-secondary);
  transition: all 0.2s;
  opacity: 0;
}
.sidebar:hover .collapse-button {
  opacity: 1;
}
.collapse-button:hover {
  background-color: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}
.collapse-button .el-icon {
  font-size: 16px;
}
.sidebar-header.is-collapsed .collapse-button {
  right: 10px;
}
.sidebar-header:not(.is-collapsed) .collapse-button {
  right: 10px;
}


.content-panel {
  padding: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  padding-left: 20px;
  border-left: 1px solid var(--el-border-color-light);
}

.main-toolbar {
  position: absolute;
  top: 20px;
  right: 20px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--el-text-color-primary);
}

.content-panel > *:not(.main-toolbar) {
  flex-grow: 1;
  padding: 20px 20px 20px 0;
  overflow-y: auto;
}

</style>