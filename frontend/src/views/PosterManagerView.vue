<template>
  <div class="poster-manager-page">
    <div class="page-header">
      <h2>海报管理器</h2>
      <p>系统性地管理您的媒体图片（海报、Logo、背景图）。提供从 Emby 到 GitHub 的备份、恢复及精细化单体管理功能，确保您的图片资产安全可控。</p>
    </div>
    <div class="top-actions">
      <el-button size="large" @click="isSingleManageDialogVisible = true">查找单个媒体进行管理...</el-button>
      <el-button size="large" @click="isConfigDialogVisible = true">配置中心</el-button>
    </div>
    <div class="main-content-area">
      <div class="left-panel">
        <el-card class="box-card action-card" shadow="never">
          <template #header>
            <div class="card-header"><span>批量操作</span></div>
          </template>
          <div class="action-form">
            <div class="scope-selector">
              <p class="form-label">目标范围</p>
              <el-radio-group v-model="batchScope.mode">
                <el-radio value="latest">最新入库</el-radio>
                <el-radio value="favorites">仅收藏</el-radio>
                <el-radio value="all">所有媒体库</el-radio>
                <el-radio value="by_type">按媒体类型</el-radio>
                <el-radio value="by_library">按媒体库</el-radio>
                <el-radio value="by_search">按搜索/ID</el-radio>
              </el-radio-group>
            </div>
            <div class="content-selector">
              <p class="form-label">内容类型</p>
              <el-checkbox-group v-model="selectedContentTypes">
                <el-checkbox value="poster">海报 (Poster)</el-checkbox>
                <el-checkbox value="logo">Logo (Clearlogo)</el-checkbox>
                <el-checkbox value="fanart">背景图 (Fanart)</el-checkbox>
              </el-checkbox-group>
            </div>
            <div class="button-group">
              <el-button type="primary" @click="handleBackup" :loading="isLoading">开始备份到 GitHub</el-button>
              <el-button type="success" @click="handleRestore" :loading="isLoading">从 GitHub 恢复到 Emby</el-button>
            </div>
          </div>
        </el-card>
      </div>
      <div class="right-panel">
        <div class="stats-cards-container" v-loading="store.isStatsLoading">
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
        <div class="charts-container" v-loading="store.isStatsLoading">
          <el-card class="chart-card">
            <template #header><div class="card-header"><el-icon><PieChart /></el-icon> 图片类型分布</div></template>
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
            <template #header><div class="card-header"><el-icon><DataAnalysis /></el-icon> <span>仓库容量概览</span>
                <!-- --- 新增代码块 --- -->
                <el-button 
                  :icon="Refresh" 
                  circle 
                  text 
                  :loading="store.isStatsLoading"
                  @click="store.fetchStats"
                  style="margin-left: auto;"
                  title="刷新状态"
                /></div></template>
            <div class="repo-list-wrapper">
              <div v-for="(repo, index) in store.stats.repo_details" :key="index" class="repo-item">
                <span class="repo-name">{{ repo.name }}</span>
                <el-progress :percentage="getRepoPercent(repo)" :stroke-width="15" :show-text="false" :color="getRepoColor(repo)" class="repo-progress" />
                <span class="repo-size">{{ store.formatBytes(repo.used_bytes) }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </div>

    <PosterManagerConfigDialog v-model:visible="isConfigDialogVisible" />
    <PosterManagerSingleDialog v-model:visible="isSingleManageDialogVisible" />
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue';
import { usePosterManagerStore } from '@/stores/posterManager';
import { ElMessage } from 'element-plus';
import { PieChart, DataAnalysis, Refresh } from '@element-plus/icons-vue';
import PosterManagerConfigDialog from '@/components/PosterManagerConfigDialog.vue';
import PosterManagerSingleDialog from '@/components/PosterManagerSingleDialog.vue';

const store = usePosterManagerStore();

const batchScope = ref({ mode: 'latest' });
const selectedContentTypes = ref(['poster', 'logo', 'fanart']);
const isLoading = ref(false);

const isConfigDialogVisible = ref(false);
const isSingleManageDialogVisible = ref(false);

onMounted(() => {
  store.fetchConfig();
  store.fetchStats();
});

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
  store.startBackup(batchScope.value, selectedContentTypes.value, store.config.overwrite_remote_files);
};

const handleRestore = () => {
  if (selectedContentTypes.value.length === 0) {
    ElMessage.warning('请至少选择一种内容类型进行恢复。');
    return;
  }
  store.startRestore(batchScope.value, selectedContentTypes.value);
};
</script>

<style scoped>
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
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.top-actions {
  display: flex;
  gap: 15px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--el-border-color-light);
  margin-bottom: 20px;
  flex-shrink: 0;
}

.main-content-area {
  flex-grow: 1;
  display: flex;
  gap: 20px;
  overflow: hidden;
}
.left-panel { width: 350px; flex-shrink: 0; }
.right-panel { flex-grow: 1; display: flex; flex-direction: column; gap: 20px; }

.box-card, .chart-card, .stat-card { 
  border: 1px solid var(--el-border-color-lighter); 
  border-radius: 12px;
}

.card-header { font-weight: bold; display: flex; align-items: center; gap: 8px; }
.action-form { display: flex; flex-direction: column; gap: 20px; }
.form-label { font-size: 14px; color: var(--el-text-color-secondary); margin-bottom: 8px; }
.button-group { display: flex; flex-direction: column; gap: 10px; }
.stats-cards-container { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }

/* --- 核心修改：调整指标卡片内部样式 --- */
.stat-card { 
  text-align: center; 
  padding: 20px; 
}
.stat-title { 
  font-size: 1rem; 
  color: var(--el-text-color-secondary); 
  margin-bottom: 8px; /* 增加与数值的间距 */
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
/* --- 结束修改 --- */

.color-green { color: #67C23A; }
.color-yellow { color: #E6A23C; }
.color-red { color: #F56C6C; }

.charts-container { 
  flex-grow: 1; 
  display: grid; 
  grid-template-columns: 1fr 1fr; 
  gap: 20px; 
  min-height: 0; /* 关键：让 flex/grid 子项能够正确地收缩 */
}

/* --- 核心修改：确保图表卡片和其内容区占满高度 --- */
.chart-card {
  display: flex;
  flex-direction: column;
}
.chart-card :deep(.el-card__body) {
  flex-grow: 1;
  padding: 20px; /* 确保有内边距 */
  display: flex; /* 让 body 也成为 flex 容器 */
  flex-direction: column; /* 内部内容垂直排列 */
}
/* --- 结束修改 --- */

.pie-charts-wrapper { 
  display: flex; 
  justify-content: space-around; 
  align-items: center;
  height: 100%; 
}
.pie-chart-item { text-align: center; }
.pie-chart-label { margin-top: 10px; font-size: 14px; }

.repo-list-wrapper { display: flex; flex-direction: column; gap: 15px; padding: 10px 0; }
.repo-item { display: flex; align-items: center; gap: 15px; }
.repo-name { width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.repo-progress { flex-grow: 1; }
.repo-size { width: 100px; text-align: right; font-family: monospace; }
</style>