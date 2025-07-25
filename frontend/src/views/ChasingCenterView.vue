<!-- frontend/src/views/ChasingCenterView.vue (完整文件覆盖) -->
<template>
  <div class="chasing-center-page">
    <div class="page-header">
      <h2>自动化追更中心</h2>
      <p>启用后，新入库的“播出中”剧集将自动加入此列表，并由定时任务每日维护剧集元数据的刷新，完结后自动移除。</p>
    </div>

    <div class="main-content">
      <!-- 左侧配置区 -->
      <div class="config-panel">
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>核心设置</span>
            </div>
          </template>
          <el-form v-if="!store.isLoading" :model="localConfig" label-position="top">
            <el-form-item>
              <div class="workflow-switch-container">
                <span class="switch-label">自动化追更工作流</span>
                <el-switch v-model="localConfig.enabled" size="large" />
              </div>
            </el-form-item>

            <el-collapse v-model="activeCollapse" accordion>
              <el-collapse-item name="1">
                <template #title>
                  <el-icon><Notification /></el-icon>  追剧维护和通知配置
                </template>
                <div class="collapse-content">
                  <!-- --- 新增 --- -->
                  <el-form-item label="每日维护周期 (CRON 表达式)">
                    <el-input 
                      v-model="localConfig.maintenance_cron" 
                      placeholder="例如: 0 3 * * *"
                      @input="() => parseCron(localConfig.maintenance_cron, 'maintenance')"
                    />
                    <div v-if="cronDescriptions.maintenance.text" class="cron-description" :class="{ 'error': cronDescriptions.maintenance.error }">
                      {{ cronDescriptions.maintenance.text }}
                    </div>
                  </el-form-item>
                  <!-- --- 新增结束 --- -->
                  <el-form-item label="日历通知周期 (CRON 表达式)">
                    <el-input 
                      v-model="localConfig.notification_cron" 
                      placeholder="例如: 0 9 * * *"
                      @input="() => parseCron(localConfig.notification_cron, 'notification')"
                    />
                     <div v-if="cronDescriptions.notification.text" class="cron-description" :class="{ 'error': cronDescriptions.notification.error }">
                      {{ cronDescriptions.notification.text }}
                    </div>
                  </el-form-item>
                  <el-form-item label="日历预告天数">
                    <el-input-number v-model="localConfig.calendar_days" :min="1" :max="30" />
                  </el-form-item>
                </div>
              </el-collapse-item>
              <el-collapse-item name="2">
                <template #title>
                  <el-icon><CircleCheck /></el-icon>  完结检测
                </template>
                 <div class="collapse-content">
                  <el-form-item label="完结等待期 (天)">
                    <el-input-number v-model="localConfig.completion_deadline_days" :min="1" />
                    <div class="form-item-description">
                      当剧集数量完整但元数据不全时，从最后一集播出日期算起，最多等待这么多天来补全元数据，超时则强制完结。
                    </div>
                  </el-form-item>
                </div>
              </el-collapse-item>
            </el-collapse>

            <div class="action-buttons">
              
            <el-button @click="handleTriggerCalendar" :disabled="!localConfig.enabled">执行一次日历通知</el-button>
              <el-button @click="handleTriggerRun" :disabled="!localConfig.enabled">立即执行一次维护</el-button>
              <el-button type="primary" @click="handleSave" :loading="store.isSaving">保存设置</el-button>
            </div>
          </el-form>
          <el-skeleton v-else :rows="5" animated />
        </el-card>
      </div>

      <!-- 右侧列表区 -->
      <div class="list-panel">
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>当前追更列表 ({{ store.chasingList.length }})</span>
              <el-button type="primary" :icon="Plus" @click="isSearchDialogVisible = true">手动添加</el-button>
            </div>
          </template>
          <div 
            class="list-card-container energy-ring-loading-container" 
            v-loading="store.isListLoading"
            element-loading-text="正在加载列表..."
            element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
          >
            <div v-if="store.chasingList.length > 0" class="card-grid">
              <ChasingCard 
                v-for="series in store.chasingList" 
                :key="series.emby_id"
                :series="series"
                @remove="series => store.removeFromList(series)"
                @view-calendar="handleViewCalendar"
              />
            </div>
            <el-empty v-else description="当前没有正在追更的剧集" />
          </div>
        </el-card>
      </div>
    </div>

    <!-- 搜索对话框 -->
    <el-dialog
      v-model="isSearchDialogVisible"
      title="手动添加追更剧集"
      width="60%"
      top="5vh"
    >
      <div class="search-dialog-content">
        <el-form @submit.prevent="handleSearch" class="search-form">
          <el-input v-model="searchQuery" placeholder="输入剧集标题..." clearable />
          <el-button type="primary" native-type="submit" :loading="mediaStore.isLoading">搜索 Emby</el-button>
        </el-form>
        <div class="search-results-table" v-loading="mediaStore.isLoading">
          <el-table
            :data="mediaStore.searchResults"
            height="100%"
            highlight-current-row
            @row-click="handleSeriesSelection"
            empty-text="请输入关键词搜索"
          >
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="70" />
          </el-table>
        </div>
      </div>
    </el-dialog>
    <CalendarDialog 
      v-model:visible="isCalendarDialogVisible"
      :series-data="selectedSeriesForCalendar"
    />

  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import { useChasingCenterStore } from '@/stores/chasingCenter';
import { useMediaStore } from '@/stores/media';
import { useConfigStore } from '@/stores/config';
import { ElMessage } from 'element-plus';
import { Notification, CircleCheck, Plus } from '@element-plus/icons-vue';
import ChasingCard from '@/components/ChasingCard.vue';
import CalendarDialog from '@/components/CalendarDialog.vue';
import _ from 'lodash';
// --- 新增 ---
import cronstrue from 'cronstrue/i18n';
// --- 新增结束 ---

const store = useChasingCenterStore();
const mediaStore = useMediaStore();
const configStore = useConfigStore();

const localConfig = ref({});
const activeCollapse = ref('1');
const isSearchDialogVisible = ref(false);
const searchQuery = ref('');

const isCalendarDialogVisible = ref(false);
const selectedSeriesForCalendar = ref(null);

// --- 新增 ---
const cronDescriptions = ref({
  maintenance: { text: '', error: false },
  notification: { text: '', error: false },
});

const parseCron = (cronValue, type) => {
  const target = cronDescriptions.value[type];
  if (!cronValue || cronValue.trim() === '') {
    target.text = '';
    target.error = false;
    return;
  }
  try {
    target.text = cronstrue.toString(cronValue, { locale: "zh_CN" });
    target.error = false;
  } catch (e) {
    target.text = `表达式无效: ${e}`;
    target.error = true;
  }
};
// --- 新增结束 ---

const handleViewCalendar = async (series) => {
  selectedSeriesForCalendar.value = series;
  await store.fetchCalendarData(series.emby_id);
  isCalendarDialogVisible.value = true;
};

onMounted(() => {
  store.fetchConfig();
  store.fetchList();
  if (!configStore.isLoaded) {
    configStore.fetchConfig();
  }
});

watch(() => store.config, (newConfig) => {
  localConfig.value = _.cloneDeep(newConfig);
  // --- 新增 ---
  // 初始化时解析一次
  parseCron(localConfig.value.maintenance_cron, 'maintenance');
  parseCron(localConfig.value.notification_cron, 'notification');
  // --- 新增结束 ---
}, { deep: true });

const handleSave = async () => {
  const success = await store.saveConfig(localConfig.value);
  if (success) {
    // ElMessage.success('配置已保存！');
  }
};

const handleTriggerRun = () => {
  store.triggerRun();
};

const handleTriggerCalendar = () => {
  store.triggerCalendar();
};

const handleSearch = () => {
  mediaStore.searchMedia(searchQuery.value).then(() => {
    mediaStore.searchResults = mediaStore.searchResults.filter(item => item.Type === 'Series');
  });
};

const handleSeriesSelection = async (series) => {
  const success = await store.addToList(series);
  if (success) {
    isSearchDialogVisible.value = false;
  }
};
</script>

<style scoped>
.chasing-center-page {
  padding: 0 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.main-content {
  display: grid;
  grid-template-columns: 450px 1fr;
  gap: 20px;
  flex-grow: 1;
  padding-top: 20px;
  overflow: hidden;
}

.config-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden; /* 确保配置面板本身不滚动 */
}
.list-panel {
  height: 100%;
  overflow: hidden; /* 确保列表面板本身不滚动 */
}

.box-card {
  height: 100%;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color-lighter);
}
.box-card :deep(.el-card__header) {
  flex-shrink: 0;
}
.box-card :deep(.el-card__body) {
  flex-grow: 1;
  overflow-y: auto; /* 让卡片内容区可以滚动 */
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}

.workflow-switch-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 10px;
  background-color: var(--el-fill-color-light);
  border-radius: 8px;
}
.switch-label {
  font-size: 1.1rem;
  font-weight: bold;
}

.el-collapse {
  margin-top: 20px;
  border-top: none;
  border-bottom: none;
}
.el-collapse :deep(.el-collapse-item__header) {
  font-size: 1rem;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.collapse-content {
  padding: 10px 5px 0 5px;
}
.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}

.action-buttons {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.list-card-container {
  height: 100%;
  overflow-y: auto; /* 关键：让卡片网格区域滚动 */
  padding: 5px; /* 为卡片阴影留出空间 */
}
.card-grid {
  display: grid;
  /* 核心修改：使用 fr 单位和 minmax 实现响应式 */
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 20px;
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
}.cron-description {
  font-size: 12px;
  color: var(--el-color-success);
  margin-top: 5px;
  padding: 5px 8px;
  background-color: var(--el-color-success-light-9);
  border-radius: 4px;
  line-height: 1.4;
}

.cron-description.error {
  color: var(--el-color-error);
  background-color: var(--el-color-error-light-9);
}
</style>