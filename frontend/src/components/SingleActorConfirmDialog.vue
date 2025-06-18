// frontend/src/components/SingleActorConfirmDialog.vue (不含style的完整代码)
<template>
  <el-dialog
    :model-value="visible"
    title="演员匹配结果确认"
    width="650px"
    :before-close="() => $emit('close')"
  >
    <div v-if="context" class="confirm-content">
      <p>系统通过作品上下文为您匹配到以下演员，请确认是否正确：</p>
      <div class="card-container">
        <!-- 上下文作品卡片 -->
        <div class="context-card media-card">
          <div class="card-header">上下文作品</div>
          <el-image 
            :src="`https://image.tmdb.org/t/p/w185${context.media.poster_path}`" 
            fit="cover" 
            class="card-poster"
          >
            <template #error>
              <div class="poster-placeholder"><el-icon><Film /></el-icon></div>
            </template>
          </el-image>
          <div class="card-info">
            <h4 class="card-title">{{ context.media.title }}</h4>
            <p class="card-subtitle">{{ context.media.year }}</p>
          </div>
        </div>

        <div class="arrow-separator">
          <el-icon><DArrowRight /></el-icon>
        </div>

        <!-- 匹配到的演员卡片 -->
        <div class="context-card person-card">
          <div class="card-header">匹配到的演员</div>
          <el-image 
            :src="`https://image.tmdb.org/t/p/w185${context.person.profile_path}`" 
            fit="cover" 
            class="card-poster"
          >
            <template #error>
              <div class="poster-placeholder"><el-icon><UserFilled /></el-icon></div>
            </template>
          </el-image>
          <div class="card-info">
            <h4 class="card-title">{{ context.person.name }}</h4>
            <p class="card-subtitle">饰: {{ context.person.character }}</p>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('reject')">否，让我手动选择</el-button>
      <el-button type="primary" @click="$emit('confirm', context.person.id)">是，获取此演员头像</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { Film, UserFilled, DArrowRight } from '@element-plus/icons-vue';

defineProps({
  visible: Boolean,
  context: { type: Object, default: null },
});
defineEmits(['update:visible', 'confirm', 'reject', 'close']);
</script>

<style scoped>
.confirm-content {
  line-height: 1.6;
}
.card-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-top: 15px;
}
.context-card {
  flex: 1;
  padding: 15px;
  background-color: var(--el-fill-color-light);
  border-radius: 8px;
  text-align: center;
}
.card-header {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 10px;
}
.card-poster {
  width: 120px;
  height: 180px;
  border-radius: 4px;
  margin: 0 auto;
  display: block;
}
.poster-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 40px;
  color: var(--el-text-color-placeholder);
}
.card-info {
  margin-top: 10px;
}
.card-title {
  margin: 0 0 5px 0;
  font-size: 16px;
  font-weight: bold;
}
.card-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.arrow-separator {
  font-size: 24px;
  color: var(--el-text-color-secondary);
}
</style>