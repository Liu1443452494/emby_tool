// frontend/src/components/ImageMagnifier.vue (最终修复版)

<template>
  <transition name="magnifier-fade">
    <div
      v-if="visible"
      class="image-magnifier"
      :style="magnifierStyle"
    >
      <el-image :src="imageUrl" fit="cover" class="magnifier-image">
        <template #placeholder>
          <div class="magnifier-placeholder">
            <el-icon class="is-loading" :size="30"><Loading /></el-icon>
          </div>
        </template>
        <template #error>
          <div class="magnifier-placeholder">
            <el-icon :size="40"><Picture /></el-icon>
          </div>
        </template>
      </el-image>
    </div>
  </transition>
</template>

<script setup>
import { computed } from 'vue';
import { Loading, Picture } from '@element-plus/icons-vue';

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  imageUrl: {
    type: String,
    default: '',
  },
  position: {
    type: Object,
    default: () => ({ x: 0, y: 0 }),
  },
  size: {
    type: Object,
    default: () => ({ width: 400, height: 600 }),
  },
});

const magnifierStyle = computed(() => ({
  width: `${props.size.width}px`,
  height: `${props.size.height}px`,
  top: `${props.position.y}px`,
  left: `${props.position.x}px`,
}));
</script>

<style scoped>
.image-magnifier {
  position: fixed;
  z-index: 9999;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  border: 2px solid rgba(255, 255, 255, 0.3);
  pointer-events: none; /* 保留此项作为双重保险 */
  
  /* 关键修改 1: 移除 transform，让 top/left 直接控制左上角 */
  /* transform: translate(-50%, -50%); */
  
  /* 关键修改 2: 设置变换原点为左上角，使缩放动画效果正确 */
  transform-origin: top left;
}

.magnifier-fade-enter-active,
.magnifier-fade-leave-active {
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
}

/* 关键修改 3: 动画只控制 scale 和 opacity */
.magnifier-fade-enter-from,
.magnifier-fade-leave-to {
  transform: scale(0.95);
  opacity: 0;
}
.magnifier-fade-enter-to,
.magnifier-fade-leave-from {
  transform: scale(1);
  opacity: 1;
}

.magnifier-image {
  width: 100%;
  height: 100%;
}

.magnifier-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}
</style>