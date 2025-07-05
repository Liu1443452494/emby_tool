<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="查找单个媒体"
    width="60%"
    top="5vh"
    class="poster-manager-search-dialog"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <div class="search-view">
      <h3 class="view-title">第一步：查找您要管理的媒体</h3>
      <div class="search-bar">
        <el-input v-model="searchQuery" placeholder="输入电影或剧集标题、ID..." clearable @keyup.enter="handleSearch" />
        <el-button type="primary" @click="handleSearch" :loading="mediaStore.isLoading">搜索 Emby</el-button>
      </div>
                <div 
        class="search-results-table energy-ring-loading-container" 
        v-loading="mediaStore.isLoading"
        element-loading-text="正在搜索..."
        element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
      >
        <el-table
          :data="mediaStore.searchResults"
          height="100%"
          highlight-current-row
          @current-change="handleSelectionChange"
          empty-text="请输入关键词进行搜索"
        >
          <el-table-column prop="Name" label="标题" />
          <el-table-column prop="ProductionYear" label="年份" width="100" />
        </el-table>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="success" @click="manageSelectedItem" :disabled="!selectedItem">管理选中的项目</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue';
import { useMediaStore } from '@/stores/media';

defineProps({ visible: Boolean });
const emit = defineEmits(['update:visible', 'manage-item']);

const mediaStore = useMediaStore();
const searchQuery = ref('');
const selectedItem = ref(null);


const handleSearch = () => {
  mediaStore.searchMedia(searchQuery.value);
};

const handleSelectionChange = (item) => {
  selectedItem.value = item;
};

const manageSelectedItem = () => {
  if (selectedItem.value) {
    emit('manage-item', selectedItem.value);
    emit('update:visible', false);
  }
};
</script>

<style scoped>
.search-view {
  display: flex;
  flex-direction: column;
}
.view-title {
  text-align: center;
  font-size: 20px;
  font-weight: 500;
  margin: 10px 0 30px 0;
}
.search-bar {
  display: flex;
  gap: 15px;
  margin-bottom: 20px;
}
.search-results-table {
  height: 50vh;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}
.dialog-footer {
  text-align: right;
}

</style>