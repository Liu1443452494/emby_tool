<template>
  <div class="image-card" :class="`type-${type}`">
    <div class="image-container">
      <el-image v-if="imageInfo" :src="imageInfo.url" fit="cover" lazy class="main-image">
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
        type="primary"
        :disabled="actionDisabled"
        @click="$emit('action')"
      >
        {{ actionText }}
      </el-button>
      <template v-else>
        <el-button
          type="success"
          :disabled="!imageInfo"
          @click="$emit('action')"
        >
          恢复到 Emby
        </el-button>
        <el-button
          type="danger"
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

<style scoped>
.image-card {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--el-fill-color-light);
}

.image-container {
  flex-grow: 1;
  position: relative;
  overflow: hidden;
}

.main-image, .image-placeholder, .image-slot-loading, .image-slot-error {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.image-placeholder {
  border: 2px dashed var(--el-border-color-light);
  border-radius: 4px;
  margin: 10px;
  box-sizing: border-box;
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
}
.action-bar .el-button {
  width: 100%;
}
</style>