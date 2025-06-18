// frontend/src/views/MediaDownloadView.vue (修改后)
<template>
  <div class="media-download-page">
    <div class="media-download-layout">
      <!-- 左侧控制面板 -->
      <div class="controls-panel">
        <h2 class="panel-title">Emby媒体下载</h2>

        <div class="control-section">
          <h3>查找单个媒体项</h3>
          <el-form @submit.prevent="handleSearch" class="control-form">
            <el-input v-model="searchQuery" placeholder="输入标题或ItemID..." clearable class="glow-input" />
            <el-button type="success" native-type="submit" :loading="mediaStore.isLoading" style="width: 100%;">
              全局搜索
            </el-button>
          </el-form>
        </div>

        <div class="divider"></div>

        <div class="control-section">
          <h3>批量下载指定范围</h3>
          <el-form label-position="top" class="control-form">
            <el-radio-group v-model="batchMode">
              <el-radio value="byType">按媒体类型</el-radio>
              <el-radio value="byLibrary">按媒体库</el-radio>
              <el-radio value="all">所有媒体库</el-radio>
            </el-radio-group>

            <div v-if="batchMode === 'byType'" class="sub-options">
              <el-radio-group v-model="batchMediaType">
                <el-radio value="Movie">仅电影</el-radio>
                <el-radio value="Series">仅电视剧</el-radio>
              </el-radio-group>
            </div>

            <div v-if="batchMode === 'byLibrary'" class="sub-options">
              <el-select v-model="selectedLibraryIds" multiple placeholder="请选择媒体库" style="width: 100%;" filterable>
                <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </div>

            <div v-if="batchMode === 'all'" class="sub-options">
              <el-input 
                v-model="libraryBlacklist" 
                type="textarea"
                :rows="2"
                placeholder="输入要排除的媒体库名称，用英文逗号(,)隔开"
              />
            </div>

            <el-button 
              v-if="!mediaStore.activeBatchTaskId"
              type="primary" 
              @click="handleBatchDownload" 
              :loading="mediaStore.isLoading" 
              style="width: 100%;"
            >
              开始批量下载
            </el-button>
            <el-button 
              v-else
              type="danger" 
              @click="handleStopBatchDownload" 
              style="width: 100%;"
            >
              停止批量下载
            </el-button>

          </el-form>
        </div>

        <div class="divider"></div>

        <div class="control-section">
          <h3>通用下载内容</h3>
          <p class="form-item-description">以下设置对“单项下载”和“批量下载”均有效。目录命名规则请在“Emby配置-下载设置”中修改。</p>
          <el-checkbox-group v-model="downloadContentTypes" class="content-checkbox-group">
            <el-checkbox value="poster">海报</el-checkbox>
            <el-checkbox value="logo">Logo</el-checkbox>
            <el-checkbox value="backdrop">背景图</el-checkbox>
            <el-checkbox value="nfo">NFO</el-checkbox>
          </el-checkbox-group>
        </div>
      </div>

      <!-- 右侧结果展示区 -->
      <div class="results-panel">
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>搜索结果</span>
            </div>
          </template>
          <div v-if="mediaStore.isLoading" class="table-skeleton-wrapper">
            <el-skeleton :rows="8" animated>
              <template #template>
                <div style="display: flex; align-items: center; justify-content: space-between; padding: 14px 0;" v-for="i in 8" :key="i">
                  <el-skeleton-item variant="text" style="width: 30%; margin-right: 16px;" />
                  <el-skeleton-item variant="text" style="width: 20%; margin-right: 16px;" />
                  <el-skeleton-item variant="text" style="width: 20%; margin-right: 16px;" />
                  <el-skeleton-item variant="text" style="width: 15%;" />
                </div>
              </template>
            </el-skeleton>
          </div>
          <el-table v-else :data="mediaStore.searchResults" style="width: 100%" height="calc(100vh - 120px)" empty-text="暂无数据，请先在左侧搜索">
            <el-table-column prop="Name" label="标题" min-width="250" />
            <el-table-column prop="ProductionYear" label="年份" width="80" />
            <el-table-column label="类型" width="120">
              <template #default="scope">
                {{ scope.row.Genres.join(', ') }}
              </template>
            </el-table-column>
            <!-- 修改开始 -->
            <el-table-column label="豆瓣ID" width="120">
                <template #default="scope">
                    {{ getProviderId(scope.row, 'douban') || '-' }}
                </template>
            </el-table-column>
            <el-table-column label="TMDB ID" width="120">
                <template #default="scope">
                    {{ getProviderId(scope.row, 'tmdb') || '-' }}
                </template>
            </el-table-column>
            <!-- 修改结束 -->
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="scope">
                <el-button
                  type="primary"
                  size="small"
                  @click="handleSingleDownload(scope.row)"
                  :loading="mediaStore.isLoading"
                >
                  下载
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { useMediaStore } from '@/stores/media';
import { useTaskStore } from '@/stores/task';
import { useStorage } from '@vueuse/core';

const mediaStore = useMediaStore();
const taskStore = useTaskStore();

const searchQuery = ref('');
const batchMode = useStorage('download-batchMode', 'byType');
const batchMediaType = useStorage('download-batchMediaType', 'Movie');
const selectedLibraryIds = useStorage('download-selectedLibraryIds', []);
const libraryBlacklist = useStorage('download-libraryBlacklist', '');
const downloadContentTypes = useStorage('download-contentTypes', ['poster', 'nfo']);

const syncTaskState = () => {
  if (mediaStore.activeBatchTaskId) {
    const taskExists = taskStore.tasks.some(task => task.id === mediaStore.activeBatchTaskId);
    if (!taskExists) {
      mediaStore.clearActiveBatchTask();
    }
  }
};

onMounted(() => {
  mediaStore.fetchLibraries();
  taskStore.connect(); 
  syncTaskState();
});

onUnmounted(() => {
  mediaStore.resetLoading();
});

const handleSearch = () => {
  mediaStore.searchMedia(searchQuery.value);
};

const handleBatchDownload = () => {
  const request = {
    mode: batchMode.value,
    content_types: downloadContentTypes.value,
    media_type: batchMode.value === 'byType' ? batchMediaType.value : null,
    library_ids: batchMode.value === 'byLibrary' ? selectedLibraryIds.value : null,
    blacklist: batchMode.value === 'all' ? libraryBlacklist.value : null,
  };
  mediaStore.startBatchDownload(request);
};

const handleSingleDownload = (row) => {
  mediaStore.downloadSingleItem(row.Id, downloadContentTypes.value);
};

const handleStopBatchDownload = async () => {
  if (mediaStore.activeBatchTaskId) {
    await taskStore.cancelTask(mediaStore.activeBatchTaskId);
    // 移除此处的 clearActiveBatchTask，交由 task.js 统一处理
  }
};

const getProviderId = (row, providerName) => {
  if (!row.ProviderIds) return null;
  const lowerProviderName = providerName.toLowerCase();
  const providerKey = Object.keys(row.ProviderIds).find(key => key.toLowerCase() === lowerProviderName);
  return providerKey ? row.ProviderIds[providerKey] : null;
};

watch(() => taskStore.tasks, () => {
  syncTaskState();
}, { deep: true });
</script>

<style scoped>
.media-download-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
  --custom-theme-color-active: #4a8a7f;
  height: 100%;
  overflow: hidden;
}

.media-download-layout { display: flex; height: 100%; }
.controls-panel {
  width: 380px;
  flex-shrink: 0;
  padding: 20px;
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}
.panel-title { margin: 0 0 10px 0; font-size: 1.8rem; }
.control-section h3 { margin: 0 0 15px 0; font-size: 1.1rem; }
.control-form { display: flex; flex-direction: column; gap: 15px; }
.divider { border-top: 1px solid var(--el-border-color-lighter); margin: 10px 0; }
.sub-options { padding: 10px 0; }

.content-checkbox-group { display: flex; flex-wrap: wrap; gap: 15px; }
.results-panel { flex-grow: 1; padding: 20px; overflow: hidden; }
.box-card { height: 100%; border: none; background-color: transparent; display: flex; flex-direction: column; }
.box-card :deep(.el-card__header) { border-bottom: none; padding: 0 0 15px 0; }
.box-card :deep(.el-card__body) { padding: 0; flex-grow: 1; overflow: hidden; }
.card-header { font-weight: bold; font-size: 1.2rem; }
.form-item-description { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-bottom: 10px; }

.table-skeleton-wrapper {
  padding: 0 10px;
  height: 100%;
  box-sizing: border-box;
}

.media-download-page :deep(.el-button--primary),
.media-download-page :deep(.el-button--success) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
  --el-button-active-bg-color: var(--custom-theme-color-active);
  --el-button-active-border-color: var(--custom-theme-color-active);
}
.media-download-page :deep(.el-radio__input.is-checked .el-radio__inner),
.media-download-page :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  border-color: var(--custom-theme-color);
  background: var(--custom-theme-color);
}
.media-download-page :deep(.el-radio__input.is-checked+.el-radio__label),
.media-download-page :deep(.el-checkbox__input.is-checked+.el-checkbox__label) {
  color: var(--custom-theme-color);
}
.media-download-page :deep(.glow-input .el-input__wrapper:hover),
.media-download-page :deep(.el-textarea__inner:hover) { 
  border-color: var(--custom-theme-color); 
}
.media-download-page :deep(.glow-input.is-focus .el-input__wrapper),
.media-download-page :deep(.el-textarea__inner:focus) {
  border-color: var(--custom-theme-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
}
.media-download-page :deep(.el-select .el-tag) {
  --el-tag-bg-color: color-mix(in srgb, var(--custom-theme-color) 20%, transparent);
  --el-tag-border-color: color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
  --el-tag-text-color: var(--custom-theme-color);
}
.media-download-page :deep(.el-select .el-tag .el-tag__close) {
  color: var(--custom-theme-color);
}
.media-download-page :deep(.el-select .el-tag .el-tag__close:hover) {
  background-color: var(--custom-theme-color);
  color: white;
}
</style>