<!-- frontend/src/views/EpisodeRenamerView.vue (最终修正版) -->
<template>
  <div class="episode-renamer-page">
    <div class="page-header">
      <h2>网盘文件重命名</h2>
      <p>将 Emby 中已更新的剧集标题同步到您的网盘文件，保持命名统一。此操作会直接修改您的网盘文件，请谨慎操作。</p>
    </div>

    <div class="toolbar">
      <div class="left-actions">
        <el-button 
          type="primary" 
          @click="handleApply" 
          :loading="store.isApplying"
          :disabled="selectedLogs.length === 0 || isTaskRunning || activeTab !== 'pending'"
        >
          应用选中项到网盘
        </el-button>
        <el-button @click="store.fetchLogs()" :loading="store.isLoading" :disabled="isTaskRunning">刷新列表</el-button>
        <el-dropdown>
          <el-button type="danger" plain>
            清理记录<el-icon class="el-icon--right"><arrow-down /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="store.clearCompletedLogs()" :disabled="completedLogs.length === 0">清理已完成记录</el-dropdown-item>
              <el-dropdown-item @click="store.clearAllLogs()" :disabled="store.logs.length === 0" divided>清理所有记录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
      <div class="right-actions">
        <el-button @click="isSettingsDialogVisible = true" :icon="Setting">设置与帮助</el-button>
      </div>
    </div>

    <!-- 布局修正：将 el-tabs 作为独立的、非伸缩的元素 -->
    <el-tabs v-model="activeTab" class="log-tabs">
      <el-tab-pane :label="`待处理任务 (${pendingLogs.length})`" name="pending"></el-tab-pane>
      <el-tab-pane :label="`已完成记录 (${completedLogs.length})`" name="completed"></el-tab-pane>
    </el-tabs>

    <!-- 布局修正：表格容器独立出来，并根据 activeTab 显示不同的数据 -->
    <div class="table-container" v-loading="store.isLoading">
      <el-table
        v-if="activeTab === 'pending'"
        :data="pendingLogs"
        style="width: 100%"
        height="100%"
        @selection-change="handleSelectionChange"
        empty-text="太棒了！没有待处理的重命名任务。"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column label="旧文件名" min-width="350">
          <template #default="scope">
            <span class="filename">{{ getBaseName(scope.row.old_base_path) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="新文件名" min-width="350">
          <template #default="scope">
            <span class="filename new-filename">{{ getBaseName(scope.row.new_base_path) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="记录时间" width="200">
          <template #default="scope">
            {{ new Date(scope.row.timestamp).toLocaleString() }}
          </template>
        </el-table-column>
      </el-table>

      <el-table
        v-if="activeTab === 'completed'"
        :data="completedLogs"
        style="width: 100%"
        height="100%"
        empty-text="暂无已完成的记录。"
      >
        <el-table-column label="旧文件名" min-width="350">
          <template #default="scope">
            <span class="filename">{{ getBaseName(scope.row.old_base_path) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="新文件名" min-width="350">
          <template #default="scope">
            <span class="filename new-filename">{{ getBaseName(scope.row.new_base_path) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="记录时间" width="200">
          <template #default="scope">
            {{ new Date(scope.row.timestamp).toLocaleString() }}
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 设置与帮助对话框 (内容不变) -->
    <el-dialog v-model="isSettingsDialogVisible" title="设置与帮助" width="700px">
      <el-tabs>
        <el-tab-pane label="路径与冷却">
          <el-form :model="localConfig" label-position="top" style="padding-top: 10px;">
            <el-form-item label="网盘操作冷却时间 (秒)">
              <el-input-number v-model="localConfig.clouddrive_rename_cooldown" :min="0" :step="0.5" :precision="1" />
              <div class="form-item-description">为防止网盘风控，每次重命名操作之间的等待时间。</div>
            </el-form-item>
            <el-form-item label="Emby 媒体根路径">
              <el-input v-model="localConfig.emby_path_root" placeholder="/media" />
              <div class="form-item-description">Emby 和本工具容器内看到的媒体根路径。</div>
            </el-form-item>
            <el-form-item label="CloudDrive 挂载根路径">
              <el-input v-model="localConfig.clouddrive_path_root" placeholder="/cd2" />
              <div class="form-item-description">CloudDrive 挂载到本工具容器内的根路径。</div>
            </el-form-item>
            <el-alert title="重要：路径映射说明" type="warning" :closable="false" show-icon>
              <p>本工具需要知道如何将 Emby 中的文件路径转换为您实际的网盘挂载路径。请确保以下配置与您的 <code>docker-compose.yml</code> 文件中的 <code>volumes</code> 映射一致。</p>
              <pre class="code-example">
services:
  emby-toolkit-backend:
    volumes:
      - /path/to/your/emby/media:{{ localConfig.emby_path_root }}
      - /path/to/your/clouddrive/mount:{{ localConfig.clouddrive_path_root }}</pre>
            </el-alert>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="后缀识别配置">
          <div style="padding-top: 10px;">
            <p class="form-item-description">
              当文件名中出现以下关键词且无空格时，系统会将其识别为“后缀”而非“标题”，从而在重命名时予以保留。
            </p>
            
            <el-divider content-position="left">内置后缀 (不可删除)</el-divider>
            <div class="suffix-tags">
              <el-tag 
                v-for="tag in KNOWN_SUFFIX_KEYWORDS" 
                :key="tag" 
                type="info" 
                effect="plain"
                style="margin-right: 8px; margin-bottom: 8px;"
              >
                {{ tag }}
              </el-tag>
            </div>

            <el-divider content-position="left">自定义后缀</el-divider>
            <TagInput 
              v-model="localConfig.custom_known_suffixes" 
              placeholder="输入新后缀并回车..." 
            />
            <div class="form-item-description" style="margin-top: 10px;">
              输入如 "MyGroup" 并回车添加。不区分大小写。
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="手动查找与匹配 (保底功能)">
          <div style="padding-top: 10px;">
            <p class="form-item-description">当 `rename_log.json` 文件丢失或损坏时，可使用此功能手动扫描指定剧集，找出需要重命名的文件。</p>
            <el-button type="danger" plain @click="isManualScanDialogVisible = true">打开手动扫描工具</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="isSettingsDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveConfig">保存设置</el-button>
      </template>
    </el-dialog>

    <!-- 手动扫描对话框 (内容不变) -->
    <el-dialog v-model="isManualScanDialogVisible" title="手动查找需要重命名的剧集" width="60%">
      <div class="manual-scan-dialog-content">
        <el-form @submit.prevent="handleSearch" class="search-form">
          <el-input v-model="searchQuery" placeholder="输入剧集标题或ID..." clearable />
          <el-button type="primary" native-type="submit" :loading="store.isSearching">搜索剧集</el-button>
        </el-form>
        <div class="search-results-table" v-loading="store.isSearching">
          <el-table :data="store.searchResults" height="100%" empty-text="请输入关键词搜索剧集">
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="80" />
            <el-table-column label="操作" width="150">
              <template #default="scope">
                <el-button 
                  type="success" 
                  size="small" 
                  @click="handleManualScan(scope.row)"
                  :loading="store.isScanning"
                  :disabled="isTaskRunning"
                >
                  扫描此剧集
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue';
import { useEpisodeRenamerStore } from '@/stores/episodeRenamer';
import { useConfigStore } from '@/stores/config';
import { useTaskStore } from '@/stores/task';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Setting, ArrowDown } from '@element-plus/icons-vue';
import TagInput from '@/components/common/TagInput.vue';

const KNOWN_SUFFIX_KEYWORDS = [
    "HHWEB", "ADWEB", "CHDWEB", "UBWEB"
];
import _ from 'lodash';

const store = useEpisodeRenamerStore();
const configStore = useConfigStore();
const taskStore = useTaskStore();

const activeTab = ref('pending');
const selectedLogs = ref([]);
const isSettingsDialogVisible = ref(false);
const isManualScanDialogVisible = ref(false);
const searchQuery = ref('');
const localConfig = ref({
  emby_path_root: '/media',
  clouddrive_path_root: '/cd2',
  clouddrive_rename_cooldown: 1.0,
  custom_known_suffixes: []
});

const isTaskRunning = computed(() => 
  taskStore.tasks.some(task => task.name.includes('重命名') && task.status === 'running')
);

const pendingLogs = computed(() => store.logs.filter(log => log.status === 'pending_clouddrive_rename'));
const completedLogs = computed(() => store.logs.filter(log => log.status === 'completed'));

onMounted(() => {
  store.fetchLogs();
  taskStore.connect();
  watch(() => configStore.appConfig.episode_renamer_config, (newConfig) => {
    if (newConfig) {
      localConfig.value = _.cloneDeep(newConfig);
    }
  }, { immediate: true, deep: true });
});

watch(isTaskRunning, (newValue, oldValue) => {
  if (oldValue && !newValue) {
    ElMessage.success('相关任务已结束，正在刷新列表...');
    setTimeout(() => {
      store.fetchLogs();
    }, 1000);
  }
});

const handleSelectionChange = (selection) => {
  selectedLogs.value = selection;
};

const getBaseName = (path) => {
  if (!path) return '';
  return path.split(/[\\/]/).pop();
};

const handleApply = async () => {
  try {
    await ElMessageBox.confirm(
      `即将对选中的 ${selectedLogs.value.length} 个项目对应的网盘文件进行重命名。此操作不可逆，是否继续？`,
      '确认操作',
      { confirmButtonText: '确定应用', cancelButtonText: '取消', type: 'warning' }
    );
    store.applyToCloudDrive(selectedLogs.value);
  } catch (error) {
    // 用户取消
  }
};

const handleSaveConfig = async () => {
  const result = await configStore.saveEpisodeRenamerConfig(localConfig.value);
  if (result.success) {
    ElMessage.success(result.message);
    isSettingsDialogVisible.value = false;
  } else {
    ElMessage.error(`保存失败: ${result.message}`);
  }
};

const handleSearch = () => {
  store.searchMedia(searchQuery.value);
};

const handleManualScan = (row) => {
  store.manualScan(row.Id);
};
</script>

<style scoped>
.episode-renamer-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
  --custom-theme-color-active: #4a8a7f;
}

.episode-renamer-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 0 20px;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 0;
  flex-shrink: 0;
}
.left-actions, .right-actions {
  display: flex;
  gap: 15px;
}

/* 布局修正：移除 flex 布局，让 tabs 和 table-container 成为块级元素，自然上下排列 */
.log-tabs {
  flex-grow: 0; /* 不再伸缩 */
  flex-shrink: 0;
}
.log-tabs :deep(.el-tabs__header) {
  margin: 0; /* 移除 header 的下边距 */
}
.log-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px; /* 将底部分割线变细 */
}

.table-container {
  flex-grow: 1; /* 让表格容器占据所有剩余空间 */
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  margin-top: 15px; /* 增加与 tabs 的间距 */
}

.filename {
  font-family: 'Courier New', Courier, monospace;
}
.new-filename {
  color: var(--el-color-success);
}

.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}
.code-example {
  background-color: var(--el-fill-color);
  padding: 10px;
  border-radius: 4px;
  margin-top: 10px;
  font-family: 'Courier New', Courier, monospace;
  white-space: pre-wrap;
}

.manual-scan-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
  height: 60vh;
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

.episode-renamer-page :deep(.el-button--primary) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
  --el-button-active-bg-color: var(--custom-theme-color-active);
  --el-button-active-border-color: var(--custom-theme-color-active);
}
.episode-renamer-page :deep(.el-tabs__item.is-active) {
  color: var(--custom-theme-color);
}
.episode-renamer-page :deep(.el-tabs__active-bar) {
  background-color: var(--custom-theme-color);
}
.episode-renamer-page :deep(.el-table__row .el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--custom-theme-color);
  border-color: var(--custom-theme-color);
}
</style>