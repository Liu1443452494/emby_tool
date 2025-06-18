// frontend/src/views/PlaceholderView.vue (新文件)
<template>
  <div class="placeholder-container">
    <h1>{{ pageTitle }}</h1>
    <p>此功能正在开发中...</p>
    <el-empty description="敬请期待" />
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();

// 根据路由名称显示不同的标题
const pageTitle = computed(() => {
  switch (route.name) {
    case 'media-download':
      return 'Emby媒体下载';
    case 'genre-mapper':
      return '类型替换';
    case 'actor-localizer':
      return '演员中文化';
    case 'logs':
      return '应用日志';
    default:
      return '开发中';
  }
});
</script>

<style scoped>
.placeholder-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--el-text-color-secondary);
}
</style>