<template>
  <div class="media-download-page">
    <div class="media-download-layout">
      <!-- 左侧控制面板 -->
      <div class="controls-panel">
        <h2 class="panel-title">Emby媒体下载</h2>

        <!-- 1. 单个搜索 (保留) -->
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

        <!-- 2. 批量下载 (重构：标准范围选择) -->
        <div class="control-section">
          <h3>批量下载指定范围</h3>
          <el-form label-position="top" class="control-form">
            
            <!-- 范围模式选择 -->
            <el-form-item label="范围模式">
              <el-select v-model="scopeMode" placeholder="请选择范围模式" style="width: 100%;">
                <el-option label="最新入库 (Latest)" value="latest" />
                <el-option label="按媒体库 (By Library)" value="by_library" />
                <el-option label="按媒体类型 (By Type)" value="by_type" />
                <el-option label="按搜索结果 (By Search)" value="by_search" />
                <el-option label="仅收藏 (Favorites)" value="favorites" />
                <el-option label="所有媒体库 (All)" value="all" />
              </el-select>
            </el-form-item>

            <!-- 动态参数区域 (直接嵌入表单，无额外样式容器) -->
            
            <!-- 最新入库参数 -->
            <template v-if="scopeMode === 'latest'">
              <el-form-item label="最近天数">
                <el-input-number v-model="scopeDays" :min="1" :max="3650" style="width: 100%;" />
              </el-form-item>
              <el-form-item label="数量限制">
                <el-input-number v-model="scopeLimit" :min="1" :max="10000" style="width: 100%;" />
              </el-form-item>
            </template>

            <!-- 按媒体库参数 -->
            <template v-if="scopeMode === 'by_library'">
              <el-form-item label="选择媒体库">
                <el-select v-model="scopeLibraryIds" multiple placeholder="请选择" style="width: 100%;">
                  <el-option v-for="lib in mediaStore.libraries" :key="lib.id" :label="lib.name" :value="lib.id" />
                </el-select>
              </el-form-item>
            </template>

            <!-- 按媒体类型参数 -->
            <template v-if="scopeMode === 'by_type'">
              <el-form-item label="媒体类型">
                <el-radio-group v-model="scopeMediaType">
                  <el-radio value="Movie">电影 (Movie)</el-radio>
                  <el-radio value="Series">剧集 (Series)</el-radio>
                </el-radio-group>
              </el-form-item>
            </template>

            <!-- 按搜索结果参数 -->
            <template v-if="scopeMode === 'by_search'">
              <el-form-item label="搜索关键词">
                <el-input v-model="scopeSearchKeyword" placeholder="输入标题或ID" clearable />
                <div class="form-item-description">
                  注意：此模式会先在前端执行搜索，然后将结果ID传给后台任务。
                </div>
              </el-form-item>
            </template>

            <!-- 所有媒体库参数 -->
            <template v-if="scopeMode === 'all'">
              <el-form-item label="排除媒体库 (黑名单)">
                <el-input 
                  v-model="scopeLibraryBlacklist" 
                  placeholder="输入库名，逗号分隔" 
                  clearable 
                />
              </el-form-item>
            </template>

            <div class="divider-dashed"></div>
            
            <!-- 下载内容选项 -->
            <el-form-item label="下载内容类型">
              <el-checkbox-group v-model="downloadContentTypes" class="content-checkbox-group">
                <el-checkbox value="poster">海报</el-checkbox>
                <el-checkbox value="logo">Logo</el-checkbox>
                <el-checkbox value="backdrop">背景图</el-checkbox>
                <el-checkbox value="nfo">NFO</el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <!-- 操作按钮 -->
            <el-button 
              v-if="!mediaStore.activeBatchTaskId"
              type="primary" 
              @click="handleBatchDownload" 
              :loading="mediaStore.isLoading" 
              style="width: 100%; margin-top: 10px;"
            >
              开始批量下载
            </el-button>
            <el-button 
              v-else
              type="danger" 
              @click="handleStopBatchDownload" 
              style="width: 100%; margin-top: 10px;"
            >
              停止批量下载
            </el-button>

          </el-form>
        </div>

      </div>

      <!-- 右侧结果展示区 (保持不变) -->
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
                {{ scope.row.Genres ? scope.row.Genres.join(', ') : '' }}
              </template>
            </el-table-column>
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
import { ElMessage } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';

const mediaStore = useMediaStore();
const taskStore = useTaskStore();

// 单个搜索
const searchQuery = ref('');

// 批量下载 - 范围选择 (与 DoubanFixer 保持一致)
const scopeMode = useStorage('download-scope-mode', 'latest');
const scopeDays = useStorage('download-scope-days', 7);
const scopeLimit = useStorage('download-scope-limit', 100);
const scopeMediaType = useStorage('download-scope-mediaType', 'Movie');
const scopeLibraryIds = useStorage('download-scope-libraryIds', []);
const scopeLibraryBlacklist = useStorage('download-scope-libraryBlacklist', '');
const scopeSearchKeyword = ref(''); // 不持久化搜索词

// 下载内容
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

const handleBatchDownload = async () => {
  // 构建 ScheduledTasksTargetScope 对象
  const scope = {
    mode: scopeMode.value,
    days: scopeDays.value,
    limit: scopeLimit.value,
    media_type: scopeMediaType.value,
    library_ids: scopeLibraryIds.value,
    library_blacklist: scopeLibraryBlacklist.value,
    item_ids: []
  };

  // 特殊处理：按搜索结果
  if (scopeMode.value === 'by_search') {
    if (!scopeSearchKeyword.value) {
      ElMessage.warning('请输入搜索关键词');
      return;
    }
    // 前端先执行搜索获取ID列表
    try {
      const response = await fetch(`${API_BASE_URL}/api/media/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: scopeSearchKeyword.value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '搜索失败');
      
      if (data.length === 0) {
        ElMessage.warning('未找到相关媒体，无法启动任务');
        return;
      }
      
      scope.item_ids = data.map(item => item.Id);
      ElMessage.info(`搜索到 ${scope.item_ids.length} 个项目，准备开始下载...`);
    } catch (error) {
      ElMessage.error(`搜索失败: ${error.message}`);
      return;
    }
  }

  const request = {
    scope: scope,
    content_types: downloadContentTypes.value
  };
  
  mediaStore.startBatchDownload(request);
};

const handleSingleDownload = (row) => {
  mediaStore.downloadSingleItem(row.Id, downloadContentTypes.value);
};

const handleStopBatchDownload = async () => {
  if (mediaStore.activeBatchTaskId) {
    await taskStore.cancelTask(mediaStore.activeBatchTaskId);
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
.divider-dashed { border-top: 1px dashed var(--el-border-color-lighter); margin: 10px 0; }

.content-checkbox-group { display: flex; flex-wrap: wrap; gap: 15px; }

.results-panel { flex-grow: 1; padding: 20px; overflow: hidden; }
.box-card { height: 100%; border: none; background-color: transparent; display: flex; flex-direction: column; }
.box-card :deep(.el-card__header) { border-bottom: none; padding: 0 0 15px 0; }
.box-card :deep(.el-card__body) { padding: 0; flex-grow: 1; overflow: hidden; }
.card-header { font-weight: bold; font-size: 1.2rem; }
.form-item-description { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-bottom: 5px; }

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