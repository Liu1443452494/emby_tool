<template>
  <el-dialog
    :model-value="visible"
    title="手动匹配 TMDB 演员"
    width="600px"
    :before-close="() => $emit('update:visible', false)"
  >
    <p>系统无法自动确定唯一的演员，请从以下列表中选择一个正确的条目：</p>
    <el-radio-group v-model="selectedId" class="candidate-list">
      <el-radio 
        v-for="candidate in candidates" 
        :key="candidate.id" 
        :label="candidate.id" 
        border
        class="candidate-radio"
      >
        <div class="candidate-item">
          <el-image 
            :src="`https://image.tmdb.org/t/p/w92${candidate.profile_path}`" 
            fit="cover" 
            class="candidate-poster"
          >
            <template #error>
              <div class="poster-placeholder"><el-icon><UserFilled /></el-icon></div>
            </template>
          </el-image>
          <div class="candidate-info">
            <span class="candidate-title">{{ candidate.name }}</span>
            <span v-if="candidate.known_for_department" class="candidate-dept">
              主要领域: {{ candidate.known_for_department }}
            </span>
            <span v-if="candidate.known_for_titles.length" class.candidate-known-for>
              代表作: {{ candidate.known_for_titles.join(', ') }}
            </span>
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
import { UserFilled } from '@element-plus/icons-vue';

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
.candidate-radio {
  width: 100%;
  height: auto;
  padding: 10px 15px;
  margin: 0 !important;
  display: flex;
  align-items: center;
}
.candidate-radio :deep(.el-radio__label) {
  flex-grow: 1;
  padding: 0;
  white-space: normal;
}
.candidate-item {
  display: flex;
  align-items: center;
  gap: 15px;
  width: 100%;
}
.candidate-poster {
  width: 60px;
  height: 90px;
  flex-shrink: 0;
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
  font-size: 24px;
}
.candidate-info {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.candidate-title {
  font-weight: bold;
  line-height: 1.3;
}
.candidate-dept, .candidate-known-for {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
</style>