<template>
  <div class="actor-avatar-mapper-page">
    <div class="page-header">
      <div class="header-left">
        <h2>演员头像映射器</h2>
        <p>管理、同步和恢复您为演员选择的自定义头像，避免在重建媒体库后重复劳动。</p>
      </div>
      <div class="header-right">
        <el-alert
          v-if="configStore.isLoaded && !isGithubConfigured"
          title="未配置 GitHub 仓库"
          type="warning"
          show-icon
          :closable="false"
          class="github-warning-alert"
        >
          <p>
            上传和下载功能不可用。映射表将仅保存在本地。
            <el-link type="primary" @click="navigateToRefresherConfig" style="vertical-align: baseline;">
              提示：本功能将复用“剧集元数据刷新”中的 GitHub 配置，点击此处跳转配置。
            </el-link>
          </p>
        </el-alert>
        <el-alert
          v-if="configStore.isLoaded && isGithubConfigured"
          title="已配置 GitHub 仓库"
          type="success"
          show-icon
          :closable="false"
          class="github-warning-alert"
        >
        </el-alert>
      </div>
    </div>

    <div class="main-layout">
      <!-- 左侧：通用范围选择 + 操作中心 -->
      <div class="left-panel">
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>通用目标范围</span>
              <el-tag type="info" effect="light" size="small">批量恢复时使用</el-tag>
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
            <div class="save-scope-button-container">
              <el-button type="primary" @click="handleSaveScope" :loading="isSavingScope">保存范围配置</el-button>
            </div>
          </div>
        </el-card>

        <el-card class="box-card action-center" shadow="never">
          <template #header>
            <div class="card-header">
              <span>操作中心</span>
            </div>
          </template>
          <div class="action-grid">
            <div v-for="action in actions" :key="action.key" class="action-item">
              <div class="action-icon-wrapper" :class="action.bgClass"><el-icon><component :is="action.icon" /></el-icon></div>
              <div class="action-title-wrapper">
                <h4>{{ action.title }}</h4>
                <el-tooltip :content="action.description" placement="top" effect="dark">
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-button @click="action.handler" :loading="isTaskRunning(action.taskKeyword)" :disabled="action.disabled && action.disabled()">{{ action.buttonText }}</el-button>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 右侧：映射表预览 -->
      <div class="right-panel">
        <el-card class="box-card map-preview" shadow="never">
          <template #header>
            <div class="card-header">
              <!-- --- 核心修改：在标题旁边显示总数 --- -->
              <div class="header-with-count">
                <span>头像映射表预览</span>
                <el-tag v-if="avatarMapperStore.totalMapCount > 0" type="info" size="small" effect="plain">
                  共 {{ avatarMapperStore.totalMapCount }} 条
                </el-tag>
              </div>
              <!-- --- 修改结束 --- -->
              <div class="preview-toolbar">
                <el-input v-model="mapSearchQuery" placeholder="搜索演员名..." clearable :prefix-icon="Search" />
                <el-button @click="avatarMapperStore.fetchMap()" :loading="avatarMapperStore.isLoading">刷新列表</el-button>
              </div>
            </div>
          </template>
         <div 
            class="map-list-container energy-ring-loading-container" 
            ref="mapListContainerRef"
            v-loading="avatarMapperStore.isLoading && filteredMap.length === 0"
            element-loading-text="正在加载映射表..."
            element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
          >
            <el-table
              v-if="filteredMap.length > 0"
              :data="filteredMap"
              style="width: 100%"
              height="100%"
              stripe
              @scroll="handleScroll"
              v-loading="isLazyLoading"
              element-loading-text="正在加载更多..."
              element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.8)"
            >
              <el-table-column label="头像" width="120">
                <template #default="scope">
                  <el-avatar class="actor-avatar" shape="square" :src="avatarMapperStore.getFullImageUrl(scope.row)" fit="cover">
                    <el-icon><User /></el-icon>
                  </el-avatar>
                </template>
              </el-table-column>
              <el-table-column prop="actor_name" label="演员名" sortable />
              <el-table-column prop="tmdb_id" label="TMDB ID" width="120" />
              <el-table-column label="图片来源" width="120">
                <template #default="scope">
                  <el-tag :type="scope.row.source === 'tmdb' ? 'success' : 'primary'">
                    {{ scope.row.source.toUpperCase() }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_updated" label="最后更新时间" width="180">
                 <template #default="scope">
                  {{ new Date(scope.row.last_updated).toLocaleString() }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="scope">
                  <el-button 
                    type="primary" 
                    size="small" 
                    plain
                    @click="handleSingleRestore(scope.row)"
                    :loading="isTaskRunning(`恢复-${scope.row.actor_name}`)"
                  >
                    恢复
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            
            <el-empty v-if="filteredMap.length === 0 && !avatarMapperStore.isLoading" description="本地无头像映射表或搜索无结果" />
          </div>
        </el-card>
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
import { ref, onMounted, computed, watch, markRaw } from 'vue';
import { useRouter } from 'vue-router';
import { useConfigStore } from '@/stores/config';
import { useMediaStore } from '@/stores/media';
import { useTaskStore } from '@/stores/task';
import { useActorAvatarMapperStore } from '@/stores/actorAvatarMapper';
import { storeToRefs } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Upload, Download, MagicStick, Search, QuestionFilled, User } from '@element-plus/icons-vue';
import _ from 'lodash';

const router = useRouter();

const configStore = useConfigStore();
const mediaStore = useMediaStore();
const taskStore = useTaskStore();
const avatarMapperStore = useActorAvatarMapperStore();
// --- 核心修改 1：直接从 store 中解构出需要的响应式状态 ---
const { displayedAvatarMap, isFullyLoaded } = storeToRefs(avatarMapperStore);

const scope = ref({});
const isSavingScope = ref(false);
const isSearchDialogVisible = ref(false);
const searchQuery = ref('');
const dialogSelection = ref([]);
const mapSearchQuery = ref('');

const mapListContainerRef = ref(null);
const isLazyLoading = ref(false);

// frontend/src/views/ActorAvatarMapperView.vue (函数替换)

const handleScroll = _.throttle(({ scrollTop }) => {
  if (isLazyLoading.value) return;
  
  const container = mapListContainerRef.value;
  if (!container) return;
  
  // el-table 内部滚动的元素
  const tableBodyWrapper = container.querySelector('.el-scrollbar__wrap');
  if (!tableBodyWrapper) return;

  const { scrollHeight, clientHeight } = tableBodyWrapper;
  
  if (scrollHeight - scrollTop - clientHeight < 200) {
    isLazyLoading.value = true;
    setTimeout(() => {
      if (mapSearchQuery.value) {
        loadMoreFiltered();
      } else {
        avatarMapperStore.loadMore();
      }
      isLazyLoading.value = false;
    }, 500);
  }
}, 200);

const isGithubConfigured = computed(() => {
  return !!configStore.appConfig.episode_refresher_config?.github_config?.repo_url;
});

const isTaskRunning = (keyword) => {
  return taskStore.tasks.some(t => t.name.includes('演员头像映射') && t.name.includes(keyword) && t.status === 'running');
};

// --- 核心修改 2：重构搜索和过滤逻辑 ---
const filteredMap = ref([]);
const filteredFullList = ref([]);
const itemsPerFilterLoad = 10;

const isFullyLoadedForCurrentView = computed(() => {
  if (mapSearchQuery.value) {
    return filteredMap.value.length >= filteredFullList.value.length;
  }
  return isFullyLoaded.value;
});

watch(mapSearchQuery, _.debounce((query) => {
  if (!query) {
    filteredMap.value = displayedAvatarMap.value;
    return;
  }
  const lowerQuery = query.toLowerCase();
  // 搜索时，直接从 store 的 fullAvatarMap 中过滤
  filteredFullList.value = avatarMapperStore.fullAvatarMap.filter(item => 
    item.actor_name.toLowerCase().includes(lowerQuery)
  );
  filteredMap.value = filteredFullList.value.slice(0, itemsPerFilterLoad);
}, 300));

function loadMoreFiltered() {
  if (filteredMap.value.length >= filteredFullList.value.length) return;
  const currentLength = filteredMap.value.length;
  const nextItems = filteredFullList.value.slice(currentLength, currentLength + itemsPerFilterLoad);
  filteredMap.value.push(...nextItems);
}

// 当搜索框清空时，恢复到原始的分页列表
watch(() => mapSearchQuery.value === '', (isCleared) => {
  if (isCleared) {
    filteredMap.value = displayedAvatarMap.value;
  }
});

// 当 store 中的 displayedAvatarMap 变化时（由 loadMore 触发），同步更新 filteredMap
watch(displayedAvatarMap, (newVal) => {
  if (!mapSearchQuery.value) {
    filteredMap.value = newVal;
  }
}, { deep: true });
// --- 核心修改结束 ---


const updateScopeFromConfig = () => {
  const defaultConfig = {
    mode: 'latest', days: 7, limit: 100, media_type: 'Movie',
    library_ids: [], library_blacklist: '', item_ids: []
  };
  const savedScope = configStore.appConfig.scheduled_tasks_config?.target_scope;
  scope.value = _.cloneDeep({ ...defaultConfig, ...savedScope });
};

onMounted(() => {
  mediaStore.fetchLibraries();
  avatarMapperStore.fetchMap().then(() => {
    // 初始加载后，将分页数据显示到 filteredMap
    filteredMap.value = displayedAvatarMap.value;
  });
  watch(() => configStore.isLoaded, (loaded) => {
    if (loaded) updateScopeFromConfig();
  }, { immediate: true });
});

const handleSearch = () => mediaStore.searchMedia(searchQuery.value);
const handleDialogSelectionChange = (selection) => dialogSelection.value = selection;
const confirmSearchSelection = () => {
  scope.value.item_ids = dialogSelection.value.map(item => item.Id);
  isSearchDialogVisible.value = false;
};

const navigateToRefresherConfig = () => {
  router.push('/scheduled-tasks');
  ElMessage.info('已跳转，请找到“剧集元数据刷新”任务卡片并点击设置按钮。');
};

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

const handleUpload = () => {
  avatarMapperStore.startTask('/api/actor-avatar-mapper/upload', {}, {
    message: '即将把本地的 `actor_avatar_map.json` 文件上传到 GitHub，这会覆盖远程仓库中的同名文件。是否继续？',
    title: '确认上传'
  });
};

const handleDownload = () => {
  avatarMapperStore.startTask('/api/actor-avatar-mapper/download', {}, {
    message: '即将从 GitHub 下载头像映射表，并覆盖本地的 `actor_avatar_map.json` 文件。请确保您已保存本地的未同步更改。是否继续？',
    title: '确认下载'
  }).then(() => avatarMapperStore.fetchMap());
};

const handleRestore = () => {
  avatarMapperStore.startTask('/api/actor-avatar-mapper/restore', { scope: scope.value }, {
    message: '即将根据本地的 `actor_avatar_map.json` 文件和当前选择的范围，恢复 Emby 中的演员头像。此操作会直接修改您的 Emby 数据。是否继续？',
    title: '确认恢复演员头像'
  });
};

const handleSingleRestore = (actorInfo) => {
  avatarMapperStore.startSingleRestore(actorInfo, scope.value);
};

const actions = ref([
  { 
    key: 'upload', 
    title: '1. 上传到 GitHub', 
    description: '将本地的头像映射表备份到云端 GitHub 仓库。', 
    icon: markRaw(Upload), 
    bgClass: 'bg-upload', 
    buttonText: '立即上传',
    taskKeyword: '上传',
    handler: handleUpload,
    disabled: () => !isGithubConfigured.value
  },
  { 
    key: 'download', 
    title: '2. 从 GitHub 下载', 
    description: '从云端仓库取回头像映射表，覆盖本地文件。', 
    icon: markRaw(Download), 
    bgClass: 'bg-download', 
    buttonText: '立即下载',
    taskKeyword: '下载',
    handler: handleDownload,
    disabled: () => !isGithubConfigured.value
  },
  { 
    key: 'restore', 
    title: '3. 批量恢复头像', 
    description: '使用本地映射表和左侧选择的范围，批量恢复 Emby 中的演员头像。', 
    icon: markRaw(MagicStick), 
    bgClass: 'bg-restore', 
    buttonText: '开始批量恢复',
    taskKeyword: '批量恢复',
    handler: handleRestore 
  }
]);
</script>

<style scoped>
/* 样式与 ActorRoleMapperView.vue 非常相似，直接复用 */
.actor-avatar-mapper-page {
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
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}
.header-left { flex-shrink: 1; }
.header-right { flex-shrink: 0; max-width: 500px; margin-right: 60px; }
.github-warning-alert { padding: 8px 12px; }
.github-warning-alert p { margin: 0; line-height: 1.6; }
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
.box-card { border: 1px solid var(--el-border-color-lighter); }
.card-header { display: flex; justify-content: space-between; align-items: center; font-weight: bold; }
.scope-selector { display: flex; flex-direction: column; gap: 20px; }
.scope-radio-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.sub-options { padding-left: 10px; border-left: 2px solid var(--el-border-color-lighter); }
.latest-options { display: flex; flex-direction: column; gap: 15px; align-items: flex-start; }
.latest-options .el-form-item { margin-bottom: 0; }
.option-unit { margin-left: 10px; }
.selection-count-text { margin-left: 15px; color: var(--el-text-color-secondary); font-size: 14px; }
.save-scope-button-container { margin-top: 10px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 20px; }
.save-scope-button-container .el-button { width: 100%; }
.action-center { flex-shrink: 0; }
.action-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
.action-item { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 8px; }
.action-icon-wrapper { width: 23px; height: 23px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.action-icon-wrapper .el-icon { font-size: 15px; color: white; }
.bg-upload { background-color: #67C23A; }
.bg-download { background-color: #E6A23C; }
.bg-restore { background-color: #F56C6C; }
.action-title-wrapper { display: flex; align-items: center; justify-content: center; gap: 8px; }
.action-title-wrapper h4 { margin: 0; font-size: 0.9rem; }
.help-icon { color: var(--el-text-color-secondary); cursor: pointer; }
.map-preview { flex-grow: 1; display: flex; flex-direction: column; overflow: hidden; }
.map-preview > :deep(.el-card__body) { flex-grow: 1; overflow: hidden; display: flex; flex-direction: column; padding: 0; }
.preview-toolbar { display: flex; gap: 10px; padding: 10px 20px; border-bottom: 1px solid var(--el-border-color-lighter); }
.map-list-container {
  flex-grow: 1;
  overflow-y: auto;
}
.search-dialog-content { display: flex; flex-direction: column; gap: 15px; height: 65vh; }
.search-form { display: flex; gap: 10px; flex-shrink: 0; }
.search-results-table { flex-grow: 1; border: 1px solid var(--el-border-color-light); border-radius: 4px; overflow: hidden; }
.actor-avatar {
  width: 98px;
  height: 148px;
  flex-shrink: 0;
  border-radius: 4px;
}
.actor-avatar :deep(img) {
  object-fit: cover;
}
.load-more-sentinel {
  padding: 20px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.load-more-sentinel.all-loaded {
  color: var(--el-color-success);
}
.load-more-sentinel :deep(.el-loading-mask) {
  background-color: transparent;
}
.load-more-sentinel :deep(.el-loading-spinner .circular) {
  width: 24px;
  height: 24px;
}
.header-with-count {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>