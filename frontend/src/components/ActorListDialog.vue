// frontend/src/components/ActorListDialog.vue (不含style的完整代码)
<template>
  <el-dialog
    :model-value="visible"
    title="请从作品演职员中选择正确的演员"
    width="700px"
    :before-close="() => $emit('close')"
  >
    <p>系统无法在作品中按姓名精确匹配，可能因为 Emby 内的名称与 TMDB 不符。请从下方演职员列表中手动选择正确的演员。</p>
    <div class="actor-list-container">
      <div 
        v-for="candidate in candidates" 
        :key="candidate.id" 
        class="actor-item"
        :class="{ selected: selectedId === candidate.id }"
        @click="selectedId = candidate.id"
      >
        <el-image 
          :src="`https://image.tmdb.org/t/p/w92${candidate.profile_path}`" 
          fit="cover" 
          class="actor-avatar"
        >
          <template #error>
            <div class="avatar-placeholder"><el-icon><UserFilled /></el-icon></div>
          </template>
        </el-image>
        <div class="actor-info">
          <span class="actor-name">{{ candidate.name }}</span>
          <span v-if="candidate.known_for_titles.length && candidate.known_for_titles[0]" class="actor-role">
            饰: {{ candidate.known_for_titles[0] }}
          </span>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('reject')">这里没有，进行全局搜索</el-button>
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
const emit = defineEmits(['update:visible', 'confirm', 'reject', 'close']);

const selectedId = ref(null);

const handleConfirm = () => {
  emit('confirm', selectedId.value);
};
</script>

<style scoped>
.actor-list-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  max-height: 60vh;
  overflow-y: auto;
  padding: 5px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}
.actor-item {
  display: flex;
  align-items: center;
  gap: 15px;
  padding: 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: background-color 0.2s, border-color 0.2s;
}
.actor-item:hover {
  background-color: var(--el-fill-color-light);
}
.actor-item.selected {
  border-color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}
.actor-avatar {
  width: 60px;
  height: 90px;
  flex-shrink: 0;
  border-radius: 4px;
  background-color: var(--el-fill-color-light);
}
.avatar-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: var(--el-text-color-secondary);
  font-size: 24px;
}
.actor-info {
  display: flex;
  flex-direction: column;
  gap: 5px;
  overflow: hidden;
}
.actor-name {
  font-weight: bold;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.actor-role {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>