<!-- frontend/views/PosterManagerView.vue (完整文件覆盖) -->
<template>
  <div class="poster-manager-page">
    <div class="page-header">
      <h2>海报管理器</h2>
      <p>系统性地管理您的媒体图片（海报、Logo、背景图）。提供从 Emby 到 GitHub 的备份、恢复及精细化单体管理功能，确保您的图片资产安全可控。</p>
    </div>
    <!-- 核心修改：调整顶部操作栏布局 -->
    <div class="top-actions">
      <div class="left-action-group">
        <el-button size="large" @click="isSearchDialogVisible = true">查找单个媒体进行管理...</el-button>
        <el-button size="large" @click="handleBackup" :loading="isLoading" class="button-backup">开始备份到 GitHub</el-button>
        <el-button size="large" @click="handleRestore" :loading="isLoading" class="button-restore">从 GitHub 恢复到 Emby</el-button>
      </div>
      <el-button size="large" @click="isConfigDialogVisible = true">配置中心</el-button>
    </div>
    <div class="main-content-area">
      <div class="left-panel">
        <el-card class="box-card action-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>批量操作</span>
              <el-tag type="info" effect="light" size="small">目标范围</el-tag>
            </div>
          </template>
          <div class="action-form">
            <div class="scope-selector">
              <el-radio-group v-model="batchScope.mode" class="scope-radio-grid">
                <el-radio value="latest">最新入库</el-radio>
                <el-radio value="favorites">仅收藏</el-radio>
                <el-radio value="all">所有媒体库</el-radio>
                <el-radio value="by_type">按媒体类型</el-radio>
                <el-radio value="by_library">按媒体库</el-radio>
                <el-radio value="by_search">按搜索/ID</el-radio>
              </el-radio-group>

              <div class="sub-options">
                <div v-if="batchScope.mode === 'latest'" class="latest-options">
                  <el-form-item label="获取最近">
                    <el-input-number v-model="batchScope.days" :min="1" controls-position="right" />
                    <span class="option-unit">天内</span>
                  </el-form-item>
                  <el-form-item label="最多处理">
                    <el-input-number v-model="batchScope.limit" :min="1" :max="500" controls-position="right" />
                    <span class="option-unit">条</span>
                  </el-form-item>
                </div>
                <div v-if="batchScope.mode === 'by_type'">
                  <el-radio-group v-model="batchScope.media_type">
                    <el-radio value="Movie">仅电影</el-radio>
                    <el-radio value="Series">仅电视剧</el-radio>
                  </el-radio-group>
                </div>
                <div v-if="batchScope.mode === 'by_library'">
                  <el-select v-model="batchScope.library_ids" multiple placeholder="请选择媒体库" style="width: 100%;"
                    filterable>
                    <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name"
                      :value="item.id" />
                  </el-select>
                </div>
                <div v-if="batchScope.mode === 'all'">
                  <el-input v-model="batchScope.library_blacklist" type="textarea" :rows="2"
                    placeholder="输入要排除的媒体库名称，用英文逗号(,)隔开" />
                </div>
                <div v-if="batchScope.mode === 'by_search'">
                  <el-button @click="openBatchSearchDialog">
                    选择媒体项...
                  </el-button>
                  <span class="selection-count-text">已选择 {{ batchScope.item_ids?.length || 0 }} 个项目</span>
                </div>
              </div>
            </div>
            <div class="content-selector">
              <p class="form-label">内容类型</p>
              <el-checkbox-group v-model="selectedContentTypes">
                <el-checkbox value="poster">海报 (Poster)</el-checkbox>
                <el-checkbox value="logo">Logo (Clearlogo)</el-checkbox>
                <el-checkbox value="fanart">背景图 (Fanart)</el-checkbox>
              </el-checkbox-group>
            </div>
            <!-- 核心修改：移除动作按钮，保留保存配置按钮 -->
            <div class="button-group">
              <el-button @click="handleSaveScope" :loading="isSavingScope"
                class="button-save-scope">保存范围与内容配置</el-button>
            </div>
          </div>
        </el-card>
      </div>
      <div class="right-panel energy-ring-loading-container" v-loading="isPanelLoading" element-loading-text="正在加载状态..."
        element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)">
        <div class="stats-cards-container">
          <el-card class="stat-card">
            <div class="stat-title">已备份图片总数</div>
            <div class="stat-value">{{ store.stats.total_images.toLocaleString() }}</div>
          </el-card>
          <el-card class="stat-card">
            <div class="stat-title">总占用空间</div>
            <div class="stat-value">{{ store.formatBytes(store.stats.total_size_bytes) }}</div>
          </el-card>
          <el-card class="stat-card">
            <div class="stat-title">仓库总数</div>
            <div class="stat-value">{{ store.stats.repo_count }}</div>
          </el-card>
          <el-card class="stat-card">
            <div class="stat-title">总空间使用百分比</div>
            <div class="stat-value" :class="percentColorClass">{{ store.totalSpaceUsedPercent }}%</div>
            <div class="stat-subtitle">{{ store.totalSpaceUsedText }}</div>
          </el-card>
        </div>
        <div class="charts-container">
          <el-card class="chart-card">
            <template #header>
              <div class="card-header"><el-icon>
                  <PieChart />
                </el-icon> 图片类型分布</div>
            </template>
            <div class="pie-charts-wrapper">
              <div class="pie-chart-item">
                <el-progress type="dashboard" :stroke-width="15" :percentage="typePercents.poster" color="#67C23A" />
                <div class="pie-chart-label">海报 ({{ store.stats.type_counts.poster }})</div>
              </div>
              <div class="pie-chart-item">
                <el-progress type="dashboard" :stroke-width="15" :percentage="typePercents.logo" color="#E6A23C" />
                <div class="pie-chart-label">Logo ({{ store.stats.type_counts.logo }})</div>
              </div>
              <div class="pie-chart-item">
                <el-progress type="dashboard" :stroke-width="15" :percentage="typePercents.fanart" color="#409EFF" />
                <div class="pie-chart-label">背景图 ({{ store.stats.type_counts.fanart }})</div>
              </div>
            </div>
          </el-card>
          <el-card class="chart-card">
            <template #header>
              <div class="card-header"><el-icon>
                  <DataAnalysis />
                </el-icon> <span>仓库容量概览</span>
                <el-button :icon="Refresh" circle text :loading="store.isStatsLoading" @click="store.fetchStats(true)"
                  style="margin-left: auto;" title="刷新状态" />
              </div>
            </template>
            <div class="repo-list-wrapper">
              <div v-for="(repo, index) in store.stats.repo_details" :key="index" class="repo-item">
                <span class="repo-name">{{ repo.name }}</span>
                <el-progress :percentage="getRepoPercent(repo)" :stroke-width="15" :show-text="false"
                  :color="getRepoColor(repo)" class="repo-progress" />
                <span class="repo-size">{{ store.formatBytes(repo.used_bytes) }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </div>

    <PosterManagerConfigDialog v-model:visible="isConfigDialogVisible" />
    <PosterManagerSingleDialog v-model:visible="isSearchDialogVisible" @manage-item="handleManageItem" />
    <PosterManagerManageViewDialog v-model:visible="isManageDialogVisible" :media-item="itemToManage"
      @back-to-search="handleBackToSearch" />

    <el-dialog v-model="isBatchSearchDialogVisible" title="选择媒体项" width="60%" top="5vh">
      <div class="search-dialog-content">
        <el-form @submit.prevent="handleBatchSearch" class="search-form">
          <el-input v-model="batchSearchQuery" placeholder="输入标题或ItemID..." clearable />
          <el-button type="primary" native-type="submit" :loading="mediaStore.isLoading">搜索</el-button>
        </el-form>
        <div class="search-results-table loading-container" v-loading="mediaStore.isLoading"
          element-loading-text="正在搜索..." :element-loading-spinner="loadingSvg"
          element-loading-svg-view-box="-10, -10, 50, 50">
          <el-table :data="mediaStore.searchResults" height="100%" @selection-change="handleBatchDialogSelectionChange"
            empty-text="请输入关键词搜索">
            <el-table-column type="selection" width="45" />
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="70" />
          </el-table>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isBatchSearchDialogVisible = false">取消</el-button>
          <el-button @click="confirmBatchSearchSelection">
            确认选择 ({{ batchDialogSelection.length }} 项)
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue';
import { usePosterManagerStore } from '@/stores/posterManager';
import { useMediaStore } from '@/stores/media';
import { useConfigStore } from '@/stores/config';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useStorage } from '@vueuse/core';
import { PieChart, DataAnalysis, Refresh } from '@element-plus/icons-vue';
import PosterManagerConfigDialog from '@/components/PosterManagerConfigDialog.vue';
import PosterManagerSingleDialog from '@/components/PosterManagerSingleDialog.vue';
import PosterManagerManageViewDialog from '@/components/PosterManagerManageViewDialog.vue';
import _ from 'lodash';

const store = usePosterManagerStore();
const mediaStore = useMediaStore();
const configStore = useConfigStore();
const batchScope = ref({});
const selectedContentTypes = useStorage('poster-manager-content-types', ['poster', 'logo', 'fanart']);
const isLoading = ref(false);
const isSavingScope = ref(false);

const isConfigDialogVisible = ref(false);
const isSearchDialogVisible = ref(false);
const isManageDialogVisible = ref(false);
const itemToManage = ref(null);

const isBatchSearchDialogVisible = ref(false);
const batchSearchQuery = ref('');
const batchDialogSelection = ref([]);

const isPanelLoading = computed(() => store.isStatsLoading || !configStore.isLoaded);

const updateScopeFromConfig = () => {
  const defaultConfig = {
    mode: 'latest',
    days: 7,
    limit: 100,
    media_type: 'Movie',
    library_ids: [],
    library_blacklist: '',
    item_ids: []
  };
  const savedScope = configStore.appConfig.scheduled_tasks_config?.target_scope;
  batchScope.value = _.cloneDeep({ ...defaultConfig, ...savedScope });
};

onMounted(() => {
  store.fetchConfig();
  store.fetchStats();
  mediaStore.fetchLibraries();
});

watch(() => configStore.isLoaded, (loaded) => {
  if (loaded) {
    updateScopeFromConfig();
  }
}, { immediate: true });

const percentColorClass = computed(() => {
  const p = store.totalSpaceUsedPercent;
  if (p > 90) return 'color-red';
  if (p > 70) return 'color-yellow';
  return 'color-green';
});

const typePercents = computed(() => {
  const total = store.stats.total_images;
  if (total === 0) return { poster: 0, logo: 0, fanart: 0 };
  return {
    poster: Math.round((store.stats.type_counts.poster / total) * 100),
    logo: Math.round((store.stats.type_counts.logo / total) * 100),
    fanart: Math.round((store.stats.type_counts.fanart / total) * 100),
  };
});


const getRepoPercent = (repo) => {
  if (!repo.threshold_bytes) return 0;
  return Math.round((repo.used_bytes / repo.threshold_bytes) * 100);
};

const getRepoColor = (repo) => {
  const p = getRepoPercent(repo);
  if (p > 90) return '#F56C6C';
  if (p > 70) return '#E6A23C';
  return '#67C23A';
};

const handleBackup = () => {
  if (selectedContentTypes.value.length === 0) {
    ElMessage.warning('请至少选择一种内容类型进行备份。');
    return;
  }
  if (batchScope.value.mode === 'by_search' && batchScope.value.item_ids.length === 0) {
    ElMessage.warning('在“按搜索/ID”模式下，请先搜索并选择媒体项。');
    return;
  }
  store.startBackup(batchScope.value, selectedContentTypes.value, store.config.overwrite_remote_files);
};

const handleRestore = () => {
  if (selectedContentTypes.value.length === 0) {
    ElMessage.warning('请至少选择一种内容类型进行恢复。');
    return;
  }
  if (batchScope.value.mode === 'by_search' && batchScope.value.item_ids.length === 0) {
    ElMessage.warning('在“按搜索/ID”模式下，请先搜索并选择媒体项。');
    return;
  }
  store.startRestore(batchScope.value, selectedContentTypes.value);
};

const openBatchSearchDialog = () => {
  if (!batchScope.value.item_ids) {
    batchScope.value.item_ids = [];
  }
  isBatchSearchDialogVisible.value = true;
  batchSearchQuery.value = '';
  mediaStore.searchResults = [];
  batchDialogSelection.value = [];
};

const handleBatchSearch = () => {
  mediaStore.searchMedia(batchSearchQuery.value);
};

const handleBatchDialogSelectionChange = (selection) => {
  batchDialogSelection.value = selection;
};

const confirmBatchSearchSelection = () => {
  batchScope.value.item_ids = batchDialogSelection.value.map(item => item.Id);
  isBatchSearchDialogVisible.value = false;
};

const handleSaveScope = async () => {
  isSavingScope.value = true;
  try {
    const configToSave = {
      target_scope: batchScope.value,
      tasks: configStore.appConfig.scheduled_tasks_config.tasks
    };
    const result = await configStore.saveScheduledTasksConfig(configToSave);
    if (result.success) {
      ElMessage.success('通用目标范围配置已保存！');
    } else {
      ElMessage.error(`保存失败: ${result.message}`);
    }
  } catch (error) {
    ElMessage.error(`保存配置时发生错误: ${error.message}`);
  } finally {
    isSavingScope.value = false;
  }
};

const handleManageItem = (item) => {
  itemToManage.value = item;
  isManageDialogVisible.value = true;
};

const handleBackToSearch = () => {
  isSearchDialogVisible.value = true;
};
</script>

<style scoped>
.poster-manager-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
  --custom-theme-color-active: #4a8a7f;
}

.poster-manager-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
  box-sizing: border-box;
}

.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0 0 8px 0;
}

.page-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

/* --- 核心修改：顶部操作栏样式 --- */
.top-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 15px;
  margin-bottom: 20px;
  flex-shrink: 0;
}

.left-action-group {
  display: flex;
  gap: 15px;
}

.main-content-area {
  flex-grow: 1;
  display: flex;
  gap: 20px;
  overflow: hidden;
}

.left-panel {
  width: 350px;
  flex-shrink: 0;
}

.right-panel {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.box-card,
.chart-card,
.stat-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
}

.card-header {
  font-weight: bold;
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-label {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.stats-cards-container {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.stat-card {
  text-align: center;
  padding: 20px;
}

.stat-title {
  font-size: 1rem;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.stat-value {
  font-size: 2.5rem;
  font-weight: bold;
}

.stat-subtitle {
  font-size: 0.8rem;
  color: var(--el-text-color-placeholder);
  margin-top: 5px;
}

.color-green {
  color: #67C23A;
}

.color-yellow {
  color: #E6A23C;
}

.color-red {
  color: #F56C6C;
}

.charts-container {
  flex-grow: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  min-height: 0;
}

.chart-card {
  display: flex;
  flex-direction: column;
}

.chart-card :deep(.el-card__body) {
  flex-grow: 1;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.pie-charts-wrapper {
  display: flex;
  justify-content: space-around;
  align-items: center;
  height: 100%;
}

.pie-chart-item {
  text-align: center;
}

.pie-chart-label {
  margin-top: 10px;
  font-size: 14px;
}

.repo-list-wrapper {
  display: flex;
  flex-direction: column;
  gap: 15px;
  padding: 10px 0;
}

.repo-item {
  display: flex;
  align-items: center;
  gap: 15px;
}

.repo-name {
  width: 150px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.repo-progress {
  flex-grow: 1;
}

.repo-size {
  width: 100px;
  text-align: right;
  font-family: monospace;
}

.sub-options {
  margin-top: 15px;
  padding-left: 10px;
  border-left: 2px solid var(--el-border-color-lighter);
}

.latest-options {
  display: flex;
  flex-direction: column;
  gap: 15px;
  align-items: flex-start;
}

.latest-options .el-form-item {
  margin-bottom: 0;
}

.option-unit {
  margin-left: 10px;
  color: var(--el-text-color-regular);
}

.selection-count-text {
  margin-left: 15px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.search-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
  height: 65vh;
}

.search-form {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.search-results-table {
  flex-grow: 1;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}

.scope-radio-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.button-group {
  margin-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.button-group .el-button {
  width: 100%;
  margin-left: 0 !important;
}

.top-actions .el-button:not(.button-backup):not(.button-restore) {
  color: var(--el-text-color-regular);
  background-color: var(--el-bg-color-overlay);
  border-color: var(--el-border-color);
}

.top-actions .el-button:not(.button-backup):not(.button-restore):hover {
  color: var(--custom-theme-color);
  border-color: color-mix(in srgb, var(--custom-theme-color) 50%, transparent);
  background-color: color-mix(in srgb, var(--custom-theme-color) 10%, transparent);
}

/* --- 备选颜色方案二：暖调灰褐色系 (增强互动感版) --- */
.button-backup {
  --el-button-text-color: #ffffff;
  --el-button-bg-color: #9e9e9e; /* 暖灰色 (基础色) */
  --el-button-border-color: #9e9e9e;
  --el-button-hover-text-color: #ffffff;
  --el-button-hover-bg-color: #bdbdbd; /* 显著提亮的灰色 (增强互动感) */
  --el-button-hover-border-color: #bdbdbd;
  --el-button-active-bg-color: #8e8e8e; /* 点击时的颜色保持深色 */
  --el-button-active-border-color: #8e8e8e;
}

.button-restore {
  --el-button-text-color: #ffffff;
  --el-button-bg-color: #a1887f; /* 浅褐色 (基础色) */
  --el-button-border-color: #a1887f;
  --el-button-hover-text-color: #ffffff;
  --el-button-hover-bg-color: #bcaaa4; /* 显著提亮的褐色 (增强互动感) */
  --el-button-hover-border-color: #bcaaa4;
  --el-button-active-bg-color: #907970; /* 点击时的颜色保持深色 */
  --el-button-active-border-color: #907970;
}

.button-save-scope {
  --el-button-text-color: var(--custom-theme-color);
  --el-button-bg-color: color-mix(in srgb, var(--custom-theme-color) 10%, transparent);
  --el-button-border-color: color-mix(in srgb, var(--custom-theme-color) 40%, transparent);
  --el-button-hover-text-color: #ffffff;
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
}

.poster-manager-page :deep(.el-radio__input.is-checked .el-radio__inner),
.poster-manager-page :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  border-color: var(--custom-theme-color);
  background: var(--custom-theme-color);
}

.poster-manager-page :deep(.el-radio__input.is-checked+.el-radio__label),
.poster-manager-page :deep(.el-checkbox__input.is-checked+.el-checkbox__label) {
  color: var(--custom-theme-color);
}

.poster-manager-page :deep(.el-select .el-tag) {
  --el-tag-bg-color: color-mix(in srgb, var(--custom-theme-color) 20%, transparent);
  --el-tag-border-color: color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
  --el-tag-text-color: var(--custom-theme-color);
}

.poster-manager-page :deep(.el-select .el-tag .el-tag__close) {
  color: var(--custom-theme-color);
}

.poster-manager-page :deep(.el-select .el-tag .el-tag__close:hover) {
  background-color: var(--custom-theme-color);
  color: white;
}

.poster-manager-page :deep(.el-dialog .el-button--primary) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
  --el-button-active-bg-color: var(--custom-theme-color-active);
  --el-button-active-border-color: var(--custom-theme-color-active);
}
</style>