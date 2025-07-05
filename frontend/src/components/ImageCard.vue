<!-- frontend/src/components/ImageCard.vue (template部分替换) -->
<template>
  <div class="image-card">
    <div 
      class="image-container" 
      :style="{ aspectRatio: type === 'poster' ? '333 / 500' : '320 / 180' }"
    >
      <el-image 
        v-if="imageInfo" 
        :src="imageInfo.url" 
        :fit="type === 'logo' ? 'contain' : 'cover'" 
        lazy 
        class="main-image"
      >
        <template #placeholder>
          <div class="image-slot-loading">
            <el-icon class="is-loading"><Loading /></el-icon>
          </div>
        </template>
        <template #error>
          <div class="image-slot-error">
            <el-icon><Picture /></el-icon>
            <span>加载失败</span>
          </div>
        </template>
      </el-image>
      <div v-else class="image-placeholder">
        <span>无 {{ typeName }}</span>
      </div>

      <div v-if="imageInfo" class="info-overlay">
        <span>{{ imageInfo.resolution || '未知分辨率' }}</span>
        <el-divider direction="vertical" />
        <span>{{ imageInfo.size || '未知大小' }}</span>
      </div>
    </div>
    <div class="action-bar">
      <el-button
        v-if="!isRemote"
        plain
        :disabled="actionDisabled"
        @click="$emit('action')"
      >
        {{ actionText }}
      </el-button>
      <template v-else>
        <el-button
          type="success"
          plain
          :disabled="!imageInfo"
          @click="$emit('action')"
        >
          恢复到 Emby
        </el-button>
        <el-button
          type="danger"
          plain
          :disabled="!imageInfo"
          @click="$emit('delete')"
        >
          删除此备份
        </el-button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { ElImage, ElButton, ElIcon, ElDivider } from 'element-plus';
import { Loading, Picture } from '@element-plus/icons-vue';

const props = defineProps({
  imageInfo: { type: Object, default: null },
  type: { type: String, required: true }, // 'poster', 'fanart', 'logo'
  isRemote: { type: Boolean, default: false },
  actionText: { type: String, default: '操作' },
  actionDisabled: { type: Boolean, default: false },
});

defineEmits(['action', 'delete']);

const typeName = computed(() => {
  const names = {
    poster: '海报',
    fanart: '背景图', 
    logo: 'Logo',
  };
  return names[props.type] || '图片';
});
</script>

/* frontend/src/components/ImageCard.vue (style块替换) */
<style scoped>
.image-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--el-fill-color-light);
}

.image-container {
  position: relative;
  overflow: hidden;
  width: 100%;
  border-radius: 6px 6px 0 0;
}

.main-image, .image-placeholder, .image-slot-loading, .image-slot-error {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* --- 新增：为 contain 模式的 logo 图片增加内边距 --- */
.main-image:deep(img[style*="contain"]) {
  padding: 10px;
  box-sizing: border-box;
}

.image-placeholder {
  color: var(--el-text-color-placeholder);
  font-size: 14px;
}

.image-slot-loading .el-icon, .image-slot-error .el-icon {
  font-size: 30px;
  color: var(--el-text-color-secondary);
}
.image-slot-error {
  flex-direction: column;
  gap: 8px;
}

.info-overlay {
  position: absolute;
  bottom: 5px;
  left: 5px;
  background-color: rgba(0, 0, 0, 0.6);
  color: white;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 5px;
  backdrop-filter: blur(2px);
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

.action-bar {
  flex-shrink: 0;
  padding: 10px;
  background-color: var(--el-bg-color-overlay);
  display: flex;
  justify-content: center;
  gap: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.action-bar .el-button {
  width: 100%;
}

/* --- 新增：为 plain 按钮定义颜色变量 --- */
.action-bar .el-button--default.is-plain {
  --el-button-text-color: var(--el-text-color-regular);
  --el-button-bg-color: var(--el-fill-color);
  --el-button-border-color: var(--el-border-color-light);
  --el-button-hover-text-color: var(--el-color-primary);
  --el-button-hover-bg-color: var(--el-color-primary-light-9);
  --el-button-hover-border-color: var(--el-color-primary-light-7);
}
</style>
