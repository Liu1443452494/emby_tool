<template>
  <el-dialog
    :model-value="visible"
    title="手动匹配 TMDB 条目"
    width="600px"
    :before-close="() => $emit('update:visible', false)"
  >
    <p>系统无法自动确定唯一的匹配项，请从以下列表中选择一个正确的条目：</p>
    <el-radio-group v-model="selectedId" class="candidate-list">
      <!-- 核心修改 1: 将 el-radio 的内容用一个 div 包裹起来，并应用新的 class -->
      <el-radio 
        v-for="candidate in candidates" 
        :key="candidate.id" 
        :label="candidate.id" 
        border
        class="candidate-radio"
      >
        <div class="candidate-item">
          <el-image 
            :src="`https://image.tmdb.org/t/p/w92${candidate.poster_path}`" 
            fit="cover" 
            class="candidate-poster"
          >
            <template #error>
              <div class="poster-placeholder"><el-icon><PictureFilled /></el-icon></div>
            </template>
          </el-image>
          <div class="candidate-info">
            <span class="candidate-title">{{ candidate.title }}</span>
            <span class="candidate-year">{{ candidate.release_date }}</span>
          </div>
        </div>
      </el-radio>
    </el-radio-group>
    <template #footer>
      <el-button @click="() => $emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="handleConfirm" :disabled="!selectedId">确认选择</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue';
import { PictureFilled } from '@element-plus/icons-vue';

defineProps({
  visible: Boolean,
  candidates: { type: Array, default: () => [] },
});
const emit = defineEmits(['update:visible', 'confirm']);

const selectedId = ref(null);

const handleConfirm = () => {
  emit('confirm', selectedId.value);
};
</script>

<style scoped>
.candidate-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 50vh;
  overflow-y: auto;
  padding: 5px;
}

/* 核心修改 2: 重写 el-radio 样式 */
.candidate-radio {
  width: 100%;
  height: auto; /* 高度自适应 */
  padding: 10px 15px;
  margin: 0 !important; /* 覆盖 el-radio-group 的默认 margin */
  display: flex; /* 让 radio 内部也使用 flex */
  align-items: center;
}

/* 覆盖 el-radio 内部的 label 样式，让我们的内容可以撑满 */
.candidate-radio :deep(.el-radio__label) {
  flex-grow: 1;
  padding: 0;
}

/* 核心修改 3: 使用 Flexbox 布局选项内容 */
.candidate-item {
  display: flex;
  align-items: center;
  gap: 15px;
  width: 100%;
}

.candidate-poster {
  width: 50px; /* 稍微增大图片宽度 */
  height: 75px; /* 保持 2:3 比例 */
  flex-shrink: 0; /* 防止图片被压缩 */
  border-radius: 4px;
  background-color: var(--el-fill-color-light);
}

.poster-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: var(--el-text-color-secondary);
}

.candidate-info {
  display: flex;
  flex-direction: column;
  gap: 5px; /* 在标题和年份之间增加一点间距 */
}

.candidate-title {
  font-weight: bold;
  line-height: 1.3;
}

.candidate-year {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>