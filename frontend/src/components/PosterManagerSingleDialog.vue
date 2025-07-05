<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="单体图片管理"
    width="auto"
    top="auto"
    class="poster-manager-dialog"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <!-- 视图一：搜索与选择 -->
    <div v-if="currentView === 'search'" class="view-container search-view">
      <h3 class="view-title">第一步：查找您要管理的媒体</h3>
      <div class="search-bar">
        <el-input v-model="searchQuery" placeholder="输入电影或剧集标题、ID..." clearable @keyup.enter="handleSearch" />
        <el-button type="primary" @click="handleSearch" :loading="mediaStore.isLoading">搜索 Emby</el-button>
      </div>
      <div class="search-results-table" v-loading="mediaStore.isLoading">
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

    <!-- 视图二：图片管理 -->
    <div v-else-if="currentView === 'manage'" class="view-container manage-view" v-loading="isFetchingDetails">
      <div class="manage-header">
        <span>当前正在管理: {{ selectedItem.Name }} ({{ selectedItem.ProductionYear }})</span>
        <el-link type="primary" :icon="ArrowLeft" @click="backToSearch">重新选择</el-link>
      </div>

      <div class="comparison-area">
        <!-- 左侧：Emby -->
        <div class="side-panel">
          <div class="panel-header">Emby</div>
          <div class="image-layout">
            <div class="poster-section">
              <ImageCard
                :image-info="embyImages.poster"
                type="poster"
                @action="handleEmbyAction('poster')"
                :action-text="getEmbyActionText('poster')"
                :action-disabled="isEmbyActionDisabled('poster')"
              />
            </div>
            <div class="right-section">
              <div class="backdrop-section">
                <ImageCard
                  :image-info="embyImages.fanart"
                  type="fanart"
                  @action="handleEmbyAction('fanart')"
                  :action-text="getEmbyActionText('fanart')"
                  :action-disabled="isEmbyActionDisabled('fanart')"
                />
              </div>
              <div class="logo-section">
                <ImageCard
                  :image-info="embyImages.logo"
                  type="logo"
                  @action="handleEmbyAction('logo')"
                  :action-text="getEmbyActionText('logo')"
                  :action-disabled="isEmbyActionDisabled('logo')"
                />
              </div>
            </div>
          </div>
        </div>

        <el-divider direction="vertical" class="main-divider" />

        <!-- 右侧：GitHub -->
        <div class="side-panel">
          <div class="panel-header">GitHub 备份</div>
          <div class="image-layout">
            <div class="poster-section">
              <ImageCard
                :image-info="githubImages.poster"
                type="poster"
                :is-remote="true"
                @action="handleGithubAction('poster', 'restore')"
                @delete="handleGithubAction('poster', 'delete')"
              />
            </div>
            <div class="right-section">
              <div class="backdrop-section">
                <ImageCard
                  :image-info="githubImages.fanart"
                  type="fanart"
                  :is-remote="true"
                  @action="handleGithubAction('fanart', 'restore')"
                  @delete="handleGithubAction('fanart', 'delete')"
                />
              </div>
              <div class="logo-section">
                <ImageCard
                  :image-info="githubImages.logo"
                  type="logo"
                  :is-remote="true"
                  @action="handleGithubAction('logo', 'restore')"
                  @delete="handleGithubAction('logo', 'delete')"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div v-if="currentView === 'search'" class="dialog-footer">
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="success" @click="manageSelectedItem" :disabled="!selectedItem">管理选中的项目</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue';
import { useMediaStore } from '@/stores/media';
import { usePosterManagerStore } from '@/stores/posterManager';
import { ArrowLeft } from '@element-plus/icons-vue';
import ImageCard from '@/components/ImageCard.vue';

defineProps({ visible: Boolean });
const emit = defineEmits(['update:visible']);

const mediaStore = useMediaStore();
const store = usePosterManagerStore();

const currentView = ref('search');
const isFetchingDetails = ref(false);
const searchQuery = ref('');
const selectedItem = ref(null);

const embyImages = ref({});
const githubImages = ref({});

const handleSearch = () => {
  mediaStore.searchMedia(searchQuery.value);
};

const handleSelectionChange = (item) => {
  selectedItem.value = item;
};

const manageSelectedItem = async () => {
  if (selectedItem.value) {
    isFetchingDetails.value = true;
    const details = await store.fetchSingleItemDetails(selectedItem.value.Id);
    if (details) {
      embyImages.value = details.emby;
      githubImages.value = details.github;
      currentView.value = 'manage';
    }
    isFetchingDetails.value = false;
  }
};

const backToSearch = () => {
  currentView.value = 'search';
  selectedItem.value = null;
  mediaStore.searchResults = [];
  searchQuery.value = '';
};

const getEmbyActionText = (type) => {
  if (!embyImages.value[type]) return '备份到 GitHub';
  if (githubImages.value[type]) {
    return store.config.overwrite_remote_files ? '覆盖远程备份' : '已存在备份';
  }
  return '备份到 GitHub';
};

const isEmbyActionDisabled = (type) => {
  if (!embyImages.value[type]) return true;
  return githubImages.value[type] && !store.config.overwrite_remote_files;
};

const handleEmbyAction = async (type) => {
  isFetchingDetails.value = true;
  const success = await store.backupSingleImage(selectedItem.value.Id, type);
  if (success) await manageSelectedItem(); // 成功后刷新详情
  isFetchingDetails.value = false;
};

const handleGithubAction = async (type, action) => {
  isFetchingDetails.value = true;
  if (action === 'restore') {
    // 恢复逻辑待实现
  } else if (action === 'delete') {
    const success = await store.deleteSingleImage(selectedItem.value.Id, type);
    if (success) await manageSelectedItem(); // 成功后刷新详情
  }
  isFetchingDetails.value = false;
};
</script>

<style>
/* 全局样式，用于实现 fit-content 效果 */
.poster-manager-dialog.el-dialog {
  width: auto; /* 使用 auto 替代 fit-content，效果更稳定 */
  min-width: 50vw; /* 新增：设置一个最小宽度，例如视口宽度的50% */
  max-width: 95vw;
  max-height: 95vh;
  margin: auto;
  display: flex;
  flex-direction: column;
}
.poster-manager-dialog .el-dialog__body {
  padding: 0;
  overflow: auto;
}
</style>

<style scoped>
.view-container {
  display: flex;
  flex-direction: column;
}
.search-view {
  padding: 20px 30px;
  box-sizing: border-box;
  height: 70vh;
  width: 100%;
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
  flex-grow: 1;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}
.dialog-footer {
  padding: 20px 30px;
  text-align: right;
  border-top: 1px solid var(--el-border-color-light);
}
.manage-view {
  padding: 20px;
}
.manage-header {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 30px;
  background-color: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color);
}
.comparison-area {
  flex-grow: 1;
  display: flex;
  overflow: hidden;
  gap: 20px;
  padding: 20px 10px;
}
.side-panel {
  display: flex;
  flex-direction: column;
}
.panel-header {
  text-align: center;
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 20px;
}
.main-divider {
  height: auto;
  margin: 20px 0;
}
.image-layout {
  display: flex;
  gap: 20px;
}
.poster-section {
  width: 333px;
  aspect-ratio: 333 / 500;
}
.right-section {
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.backdrop-section {
  aspect-ratio: 320 / 180;
}
.logo-section {
  aspect-ratio: 320 / 180;
}
</style>