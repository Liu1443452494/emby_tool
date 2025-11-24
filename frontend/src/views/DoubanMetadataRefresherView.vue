<!-- frontend/src/views/DoubanMetadataRefresherView.vue (完整文件覆盖) -->
<template>
  <div class="douban-refresher-page">
    <div class="page-header">
      <h2>豆瓣元数据刷新器</h2>
      <p>通过模拟“删除再添加”操作，强制 Emby 的豆瓣插件重新下载指定媒体的元数据，以获取最新的演员角色信息。</p>
    </div>

    <div class="main-layout">
      <!-- 左侧：通用范围选择 -->
      <div class="left-panel">
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>通用目标范围</span>
            </div>
          </template>
          <div class="scope-selector">
            <el-radio-group v-model="scope.mode" class="scope-radio-grid">
              <el-radio value="latest">最新入库</el-radio>
              <el-radio value="favorites">仅收藏</el-radio>
              <el-radio value="all">所有媒体库</el-radio>
              <el-radio value="by_type">按媒体类型</el-radio>
              <el-radio value="by_library">按媒体库</el-radio>
              <el-radio value="by_search">按搜索/ID</el-radio>
            </el-radio-group>

            <div class="sub-options">
              <div v-if="scope.mode === 'latest'" class="latest-options">
                <el-form-item label="获取最近">
                  <el-input-number v-model="scope.days" :min="1" controls-position="right" />
                  <span class="option-unit">天内</span>
                </el-form-item>
                <el-form-item label="最多处理">
                  <el-input-number v-model="scope.limit" :min="1" :max="500" controls-position="right" />
                  <span class="option-unit">条</span>
                </el-form-item>
              </div>
              <div v-if="scope.mode === 'by_type'">
                <el-radio-group v-model="scope.media_type">
                  <el-radio value="Movie">仅电影</el-radio>
                  <el-radio value="Series">仅电视剧</el-radio>
                </el-radio-group>
              </div>
              <div v-if="scope.mode === 'by_library'">
                <el-select v-model="scope.library_ids" multiple placeholder="请选择媒体库" style="width: 100%;" filterable>
                  <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </div>
              <div v-if="scope.mode === 'all'">
                <el-input v-model="scope.library_blacklist" type="textarea" :rows="2" placeholder="输入要排除的媒体库名称，用英文逗号(,)隔开" />
              </div>
              <div v-if="scope.mode === 'by_search'">
                <el-button @click="isSearchDialogVisible = true">选择媒体项...</el-button>
                <span class="selection-count-text">已选择 {{ scope.item_ids?.length || 0 }} 个项目</span>
              </div>
            </div>
            <!-- --- 新增 --- -->
            <div class="save-scope-button-container">
              <el-button type="primary" @click="handleSaveScope" :loading="isSavingScope">保存范围配置</el-button>
            </div>
            <!-- --- 新增结束 --- -->
          </div>
        </el-card>
      </div>

      <!-- 右侧：设置与操作 -->
      <div class="right-panel">
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>参数设置</span>
            </div>
          </template>
          <el-form :model="localConfig" label-position="top">
            <el-row :gutter="20">
              <el-col :span="8">
                <el-form-item label="项目间隔时间 (秒)">
                  <el-input-number v-model="localConfig.item_interval_seconds" :min="0" :step="0.5" controls-position="right" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="删除ID后等待 (秒)">
                  <el-input-number v-model="localConfig.delete_id_wait_seconds" :min="1" controls-position="right" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="写回ID后等待 (秒)">
                  <el-input-number v-model="localConfig.readd_id_wait_seconds" :min="10" controls-position="right" />
                </el-form-item>
              </el-col>
            </el-row>
            <div class="form-item-description" style="margin-top: -10px; margin-bottom: 20px;">
              <b>写回ID后等待</b> 是最关键的参数，它决定了给Emby豆瓣插件预留多少时间下载数据。如果刷新后本地文件未生成，请适当调高此值。
            </div>
            <el-divider />
            <el-form-item>
              <template #label>
                <div class="label-with-switch">
                  <span>启用后续自动化流程</span>
                  <el-switch v-model="localConfig.enable_post_refresh_actions" />
                </div>
              </template>
              <div class="form-item-description">
                开启后，对于元数据有变更的项目，将自动触发 <b>Emby元数据刷新 → 演员中文化 → 角色映射更新</b> 的完整修复链条。
              </div>
            </el-form-item>
            <el-form-item label="Emby刷新后等待 (秒)" v-if="localConfig.enable_post_refresh_actions">
              <el-input-number v-model="localConfig.emby_refresh_wait_seconds" :min="5" controls-position="right" />
              <div class="form-item-description">
                在触发Emby元数据刷新后，等待多久再执行演员中文化，以确保Emby已应用新数据。
              </div>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- --- 修改 --- -->
        <div class="action-footer">
          <el-button type="primary" @click="handleSaveConfig" :loading="isSaving" size="large">保存设置</el-button>
          <el-button type="success" @click="handleRunTask" :loading="isRunning" size="large">立即执行</el-button>
        </div>
        <!-- --- 修改结束 --- -->
      </div>
    </div>

    <!-- 搜索对话框 -->
    <el-dialog v-model="isSearchDialogVisible" title="选择媒体项" width="60%" top="5vh">
      <div class="search-dialog-content">
        <el-form @submit.prevent="handleSearch" class="search-form">
          <el-input v-model="searchQuery" placeholder="输入标题或ItemID..." clearable />
          <el-button type="primary" native-type="submit" :loading="mediaStore.isLoading">搜索</el-button>
        </el-form>
         <div 
          class="search-results-table energy-ring-loading-container" 
          v-loading="mediaStore.isLoading"
          element-loading-text="正在搜索..."
          element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
        >
          <el-table :data="mediaStore.searchResults" height="100%" @selection-change="handleDialogSelectionChange" empty-text="请输入关键词搜索">
            <el-table-column type="selection" width="45" />
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="70" />
          </el-table>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isSearchDialogVisible = false">取消</el-button>
          <el-button @click="confirmSearchSelection">确认选择 ({{ dialogSelection.length }} 项)</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue';
import { useConfigStore } from '@/stores/config';
import { useMediaStore } from '@/stores/media';
import { useTaskStore } from '@/stores/task';
import { ElMessage, ElMessageBox } from 'element-plus';
import _ from 'lodash';
import { API_BASE_URL } from '@/config/apiConfig';

const configStore = useConfigStore();
const mediaStore = useMediaStore();
const taskStore = useTaskStore();

const scope = ref({});
const localConfig = ref({});
const isSaving = ref(false);
const isRunning = ref(false);
// --- 新增 ---
const isSavingScope = ref(false);
// --- 新增结束 ---

const isSearchDialogVisible = ref(false);
const searchQuery = ref('');
const dialogSelection = ref([]);

const updateScopeFromConfig = () => {
  const defaultConfig = {
    mode: 'latest', days: 7, limit: 100, media_type: 'Movie',
    library_ids: [], library_blacklist: '', item_ids: []
  };
  const savedScope = configStore.appConfig.scheduled_tasks_config?.target_scope;
  scope.value = _.cloneDeep({ ...defaultConfig, ...savedScope });
};

const updateLocalConfig = () => {
  localConfig.value = _.cloneDeep(configStore.appConfig.douban_metadata_refresher_config);
};

onMounted(() => {
  mediaStore.fetchLibraries();
  watch(() => configStore.isLoaded, (loaded) => {
    if (loaded) {
      updateScopeFromConfig();
      updateLocalConfig();
    }
  }, { immediate: true });
});

const handleSearch = () => mediaStore.searchMedia(searchQuery.value);
const handleDialogSelectionChange = (selection) => dialogSelection.value = selection;
const confirmSearchSelection = () => {
  scope.value.item_ids = dialogSelection.value.map(item => item.Id);
  isSearchDialogVisible.value = false;
};

// --- 新增 ---
const handleSaveScope = async () => {
  isSavingScope.value = true;
  const configToSave = {
    target_scope: scope.value,
    tasks: configStore.appConfig.scheduled_tasks_config.tasks
  };
  const result = await configStore.saveScheduledTasksConfig(configToSave);
  if (result.success) {
    ElMessage.success('通用目标范围配置已保存！');
  } else {
    ElMessage.error(`保存失败: ${result.message}`);
  }
  isSavingScope.value = false;
};
// --- 新增结束 ---

const handleSaveConfig = async () => {
  isSaving.value = true;
  const result = await configStore.saveDoubanMetadataRefresherConfig(localConfig.value);
  if (result.success) {
    ElMessage.success('设置已保存！');
  } else {
    ElMessage.error(`保存失败: ${result.message}`);
  }
  isSaving.value = false;
};

const handleRunTask = async () => {
  try {
    await ElMessageBox.confirm(
      '即将开始刷新豆瓣元数据。此过程会删除并重新下载本地元数据文件，并可能触发后续自动化流程，请确认。',
      '确认执行',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info',
      }
    );

    isRunning.value = true;
    const payload = {
      scope: scope.value,
      config: localConfig.value
    };
    const response = await fetch(`${API_BASE_URL}/api/douban-metadata-refresher/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动任务失败');
    ElMessage.success(data.message);
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(`操作失败: ${error.message}`);
    }
  } finally {
    isRunning.value = false;
  }
};
</script>

<style scoped>
.douban-refresher-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0 20px;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
  margin-bottom: 20px;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.main-layout {
  flex-grow: 1;
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 20px;
  overflow: hidden;
}
.left-panel, .right-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
  padding-bottom: 20px;
}
.box-card {
  border: 1px solid var(--el-border-color-lighter);
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}
.scope-selector {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.scope-radio-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.sub-options {
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
}
.selection-count-text {
  margin-left: 15px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}
.label-with-switch {
  display: flex;
  align-items: center;
  gap: 10px;
}
/* --- 修改 --- */
.action-footer {
  margin-top: auto;
  padding-bottom: 20%; /* 将按钮组向上推 */
  display: flex;
  justify-content: center;
  gap: 20px;
}
/* --- 修改结束 --- */
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
/* --- 新增 --- */
.save-scope-button-container {
  margin-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 20px;
}
.save-scope-button-container .el-button {
  width: 100%;
}
/* --- 新增结束 --- */
</style>