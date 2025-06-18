<template>
  <el-dialog
    :model-value="visible"
    :title="dialogTitle"
    width="auto"
    top="auto"
    :before-close="handleClose"
    class="tmdb-image-manager-dialog"
  >
    <div v-if="mediaItem" class="dialog-final-layout">
      <!-- 左侧海报区域 -->
      <div class="image-section poster-section">
        <h4>海报 (Poster)</h4>
        <div class="image-wrapper poster-wrapper">
          <el-image :src="mediaItem.posterUrl" fit="cover" class="dialog-image">
            <template #error>
              <div class="image-placeholder"><el-icon><PictureFilled /></el-icon></div>
            </template>
          </el-image>
        </div>
        <!-- 核心修改：修改按钮文字和加载状态判断 -->
        <el-button 
          class="action-button" 
          plain 
          @click="onFetch('poster')"
          :loading="isLoading && currentImageType === 'poster'"
        >
          更换海报
        </el-button>
      </div>

      <!-- 右侧内容区域 (背景 + Logo) -->
      <div class="right-column">
        <!-- 背景图区域 -->
        <div class="image-section backdrop-section">
          <h4>背景 (Backdrop)</h4>
          <div class="image-wrapper backdrop-wrapper">
            <el-image :src="mediaItem.backdropUrl" fit="cover" class="dialog-image">
              <template #error>
                <div class="image-placeholder"><el-icon><PictureFilled /></el-icon></div>
              </template>
            </el-image>
          </div>
          <el-button 
            class="action-button" 
            plain 
            @click="onFetch('backdrop')"
            :loading="isLoading && currentImageType === 'backdrop'"
          >
            从 TMDB 更换
          </el-button>
        </div>

        <!-- Logo 区域 -->
        <div class="image-section logo-section">
          <h4>Logo</h4>
          <div class="image-wrapper logo-wrapper">
            <el-image :src="mediaItem.logoUrl" fit="contain" class="dialog-image">
              <template #error>
                <div class="image-placeholder"><el-icon><PictureFilled /></el-icon></div>
              </template>
            </el-image>
          </div>
          <el-button 
            class="action-button" 
            plain 
            @click="onFetch('logo')"
            :loading="isLoading && currentImageType === 'logo'"
          >
            从 TMDB 更换
          </el-button>
        </div>
      </div>
    </div>
    <el-empty v-else description="没有可用的媒体信息" />

    <template #footer>
      <el-button @click="handleClose">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue';
import { PictureFilled } from '@element-plus/icons-vue';

const props = defineProps({
  visible: { type: Boolean, required: true },
  mediaItem: { type: Object, default: null },
  isLoading: { type: Boolean, default: false },
  currentImageType: { type: String, default: '' },
});

const emit = defineEmits(['update:visible', 'fetch']);

const dialogTitle = computed(() => {
  return props.mediaItem ? `更换《${props.mediaItem.Name}》的图片` : '图片管理';
});

const handleClose = () => {
  if (props.isLoading) return;
  emit('update:visible', false);
};

const onFetch = (imageType) => {
  emit('fetch', imageType);
};
</script>

<style>
.tmdb-image-manager-dialog.el-dialog {
  width: fit-content;
  height: fit-content;
  max-width: 90vw;
  max-height: 90vh;
  --el-dialog-width: auto !important; 
  margin: auto;
  display: flex;
  flex-direction: column;
}
.tmdb-image-manager-dialog .el-dialog__body {
  padding: 25px 35px;
  overflow: auto;
}
</style>

<style scoped>
.dialog-final-layout {
  display: flex;
  align-items: center;
  gap: 40px;
}
.image-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 15px;
}
.image-section h4 {
  margin: 0 0 5px 0;
  text-align: center;
  font-size: 1rem;
  color: var(--el-text-color-primary);
}
.image-wrapper {
  border-radius: 8px;
  background-color: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-light);
  overflow: hidden;
}
.poster-section {
  width: 333px;
}
.poster-wrapper {
  width: 100%;
  aspect-ratio: 333 / 500;
}
.right-column {
  width: 320px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 30px;
}
.backdrop-wrapper, .logo-wrapper {
  width: 100%;
  aspect-ratio: 320 / 180;
}
.dialog-image {
  width: 100%;
  height: 100%;
}
.image-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  color: var(--el-text-color-secondary);
}
.dialog-image :deep(img) {
  object-fit: cover;
}
.logo-wrapper .dialog-image {
  padding: 10px;
  box-sizing: border-box;
}
.logo-wrapper .dialog-image :deep(img) {
  object-fit: contain;
}
.action-button {
  width: 80%;
  max-width: 250px;
  --el-button-text-color: var(--el-text-color-regular);
  --el-button-bg-color: var(--el-fill-color);
  --el-button-border-color: var(--el-border-color-light);
  --el-button-hover-text-color: var(--el-color-primary);
  --el-button-hover-bg-color: var(--el-color-primary-light-9);
  --el-button-hover-border-color: var(--el-color-primary-light-7);
}
</style>