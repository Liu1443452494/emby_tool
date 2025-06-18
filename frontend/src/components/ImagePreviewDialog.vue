// frontend/src/components/ImagePreviewDialog.vue
<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    :width="dialogWidth"
    @update:model-value="$emit('update:visible', $event)"
    :close-on-click-modal="false"
    top="10vh"
  >
    <div class="preview-content" v-loading="isLoading">
      <div class="preview-image-container">
        <!-- 核心修改：el-image 的 fit 属性改为 "cover" -->
        <el-image :src="imageUrl" fit="cover" class="preview-image">
          <template #placeholder>
            <div class="image-slot">加载中<span class="dot">...</span></div>
          </template>
          <template #error>
            <div class="image-slot">
              <el-icon><Picture /></el-icon>
            </div>
          </template>
        </el-image>
      </div>
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="primary" @click="$emit('confirm')">
          确认上传
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Picture } from '@element-plus/icons-vue'

const props = defineProps({
  visible: Boolean,
  title: { type: String, default: '图片预览' },
  imageUrl: { type: String, required: true },
  previewSize: { type: Object, default: () => ({ width: 400, height: 600 }) }
})

defineEmits(['update:visible', 'confirm'])

const isLoading = ref(true)

const dialogWidth = computed(() => `${400 + 60}px`)

watch(() => [props.imageUrl, props.visible], ([newUrl, newVisible]) => {
  if (newUrl && newVisible) {
    isLoading.value = true
    const img = new Image()
    img.src = newUrl
    img.onload = () => { isLoading.value = false }
    img.onerror = () => { isLoading.value = false }
  } else {
    isLoading.value = false
  }
}, { immediate: true, deep: true })
</script>

<style scoped>
.preview-content {
  display: flex;
  justify-content: center;
  align-items: center;
}

.preview-image-container {
  width: 400px;
  height: 600px;
  background-color: var(--el-fill-color-lighter);
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  display: flex;
  justify-content: center;
  align-items: center;
  overflow: hidden;
}

.preview-image {
  width: 100%;
  height: 100%;
}

/* 
  el-image 的 fit="cover" 属性会自动应用 object-fit: cover;
  所以这里的 deep 样式不再需要，但保留也无妨。
*/
.preview-image :deep(img) {
  object-fit: cover;
}

.image-slot {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.el-icon {
  font-size: 30px;
}
</style>