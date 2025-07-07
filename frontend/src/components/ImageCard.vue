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

      <!-- frontend/src/components/ImageCard.vue (部分修改) -->
      <div v-if="imageInfo" class="info-overlay">
        <!-- --- 核心修改：仅在非远程（即Emby侧）时显示分辨率 --- -->
        <span v-if="imageInfo.resolution && !isRemote" class="info-text left">{{ imageInfo.resolution }}</span>
        <span v-if="imageInfo.size && imageInfo.size !== '0.0 KB'" class="info-text right">{{ imageInfo.size }}</span>
      </div>
    </div>
    <div class="action-bar">
      <el-button
        v-if="!isRemote"
        size="small"
        :disabled="actionDisabled"
        @click="$emit('action')"
      >
        {{ actionText }}
      </el-button>
      <template v-else>
        <el-button
          type="success"
          size="small"
          :disabled="!imageInfo"
          @click="$emit('action')"
        >
          恢复到 Emby
        </el-button>
        <el-button
          type="danger"
          size="small"
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
import { ElImage, ElButton, ElIcon } from 'element-plus';
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

<style scoped>
.image-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  overflow: hidden;
  background-color: var(--el-fill-color-light);
}

.image-container {
  position: relative;
  overflow: hidden;
  width: 100%;
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
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.6) 0%, rgba(0, 0, 0, 0.4) 50%, transparent 100%);
  pointer-events: none;
}

.info-text {
  color: white;
  font-size: 12px;
  font-weight: 500;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
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
</style>