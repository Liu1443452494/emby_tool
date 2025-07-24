
<template>
  <div class="actor-role-mapper-page">
    <div class="page-header">
      <div class="header-left">
        <h2>演员角色映射器</h2>
        <p>创建、同步和恢复演员的角色名，避免在重建媒体库后重复进行翻译和修正工作。</p>
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
        <!-- 通用范围选择 -->
        <el-card class="box-card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>通用目标范围</span>
              <el-tag type="info" effect="light" size="small">生成与恢复时使用</el-tag>
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
              <el-popover
                placement="bottom-end"
                title="生成设置"
                :width="300"
                trigger="click"
              >
                <template #reference>
                  <el-button :icon="Setting" circle text class="settings-button" />
                </template>
                <div class="settings-popover">
                  <el-form-item label="演员映射条数">
                    <el-input-number v-model="actorLimit" :min="1" :max="200" controls-position="right" style="width: 100%;" />
                    <div class="form-item-description">
                      为提高效率，仅处理每个媒体项的前 N 位演员。
                    </div>
                  </el-form-item>
                  <!-- --- 新增：生成模式选择 --- -->
                  <el-divider />
                  <el-form-item label="生成模式">
                     <el-radio-group v-model="generationMode">
                        <el-radio value="incremental">增量模式</el-radio>
                        <el-radio value="overwrite">覆盖模式</el-radio>
                        <!-- --- 修改 --- -->
                        <el-radio value="update_selected">更新范围内</el-radio>
                        <!-- --- 修改结束 --- -->
                      </el-radio-group>
                      <div class="form-item-description">
                        <b>增量模式 (默认):</b> 扫描时跳过映射表中已存在的作品，仅将新发现的作品追加到文件中。适合日常更新。
                      </div>
                      <div class="form-item-description" style="margin-top: 5px;">
                        <b>覆盖模式:</b> 用本次扫描的结果完全替换旧的映射文件。适合在媒体库有大量变动或首次生成时使用。
                      </div>
                      <!-- --- 修改 --- -->
                      <div class="form-item-description" style="margin-top: 5px;">
                        <b>更新范围内:</b> 强制更新您在“通用目标范围”中选择的所有媒体项，同时保留其他已有数据。
                      </div>
                      <!-- --- 修改结束 --- -->
                  </el-form-item>
                  <!-- --- 新增结束 --- -->
                </div>
              </el-popover>
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
                <span>映射表预览</span>
                <el-tag v-if="actorRoleMapperStore.totalMapCount > 0" type="info" size="small" effect="plain">
                  共 {{ actorRoleMapperStore.totalMapCount }} 条
                </el-tag>
              </div>
              <!-- --- 修改结束 --- -->
              <div class="preview-toolbar">
                <el-input v-model="mapSearchQuery" placeholder="搜索作品或演员名..." clearable :prefix-icon="Search" />
                <el-button @click="actorRoleMapperStore.fetchMap()" :loading="actorRoleMapperStore.isLoading">刷新列表</el-button>
              </div>
            </div>
          </template>
         <div 
            class="map-list-container energy-ring-loading-container" 
            ref="mapListContainerRef"
            @scroll="handleScroll"
            v-loading="actorRoleMapperStore.isLoading && filteredMap.length === 0"
            element-loading-text="正在加载映射表..."
            element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
          >
            <el-collapse v-if="filteredMap.length > 0" v-model="activeCollapseNames" @change="handleCollapseChange">
              <el-collapse-item v-for="item in filteredMap" :key="item.tmdb_id" :name="item.tmdb_id">
                <template #title>
                  <div class="collapse-title-container">
                    <span class="collapse-title">{{ item.title }}</span>
                    <el-tag size="small" type="info" style="margin-left: 10px; flex-shrink: 0;">{{ Object.keys(item.map).length }} 位演员</el-tag>
                    <el-button 
                      class="restore-button"
                      type="primary" 
                      size="small"
                      plain
                      @click.stop="handleSingleRestore(item)"
                    >
                      恢复角色
                    </el-button>
                  </div>
                </template>
                <div class="actor-list-toolbar">
                  <el-button type="success" size="small" @click="handleSaveItem(item)" :loading="isSavingItem[item.tmdb_id]">保存此作品的修改</el-button>
                  <span class="toolbar-tip">可直接在下方表格中修改角色名</span>
                </div>
                <div class="actor-list">
                  <div v-for="(actor, name) in item.map" :key="name" class="actor-item">
                    <el-avatar :size="40" :src="getActorAvatar(item.tmdb_id, name)" shape="square">
                      <el-icon><User /></el-icon>
                    </el-avatar>
                    <span class="actor-name">{{ name }}</span>
                    <el-input v-model="actor.role" class="actor-role-input" placeholder="无角色名" />
                    <el-tag v-if="actor.tmdb_id" size="small" class="actor-tmdb-id">ID: {{ actor.tmdb_id }}</el-tag>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>

            <!-- --- 新增：加载更多提示 --- -->
            <div v-if="filteredMap.length > 0 && !isFullyLoadedForCurrentView" class="load-more-sentinel" v-loading="isLazyLoading">
              <span v-if="!isLazyLoading">滚动加载更多...</span>
            </div>
            <div v-if="filteredMap.length > 0 && isFullyLoadedForCurrentView" class="load-more-sentinel all-loaded">
              <span>🎉 已全部加载</span>
            </div>
            <!-- --- 新增结束 --- -->

            <el-empty v-if="filteredMap.length === 0 && !actorRoleMapperStore.isLoading" description="本地无映射表或搜索无结果" />
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


// frontend/src/views/ActorRoleMapperView.vue (script替换)
<script setup>
import { ref, onMounted, computed, watch, markRaw, reactive } from 'vue';
import { useRouter } from 'vue-router';
import { useConfigStore } from '@/stores/config';
import { useMediaStore } from '@/stores/media';
import { useTaskStore } from '@/stores/task';
import { useActorRoleMapperStore } from '@/stores/actorRoleMapper';
import { storeToRefs } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { DocumentAdd, Upload, Download, MagicStick, Search, QuestionFilled, User, Setting } from '@element-plus/icons-vue';
import _ from 'lodash';
import { API_BASE_URL } from '@/config/apiConfig';
import { useStorage } from '@vueuse/core';

const router = useRouter();

const configStore = useConfigStore();
const mediaStore = useMediaStore();
const taskStore = useTaskStore();
const actorRoleMapperStore = useActorRoleMapperStore();
const { isSavingItem, fullActorMap, displayedActorMap, isFullyLoaded } = storeToRefs(actorRoleMapperStore);

const scope = ref({});
const isSavingScope = ref(false);
const isSearchDialogVisible = ref(false);
const searchQuery = ref('');
const dialogSelection = ref([]);
const mapSearchQuery = ref('');
const activeCollapseNames = ref([]);
const actorLimit = useStorage('actor-role-mapper-limit', 50);
const generationMode = useStorage('actor-role-mapper-generation-mode', 'incremental');
const actorAvatarsCache = reactive({});

const mapListContainerRef = ref(null);
// --- 新增：懒加载状态 ---
const isLazyLoading = ref(false);

const handleScroll = _.throttle((event) => {
  if (isLazyLoading.value) return;
  const container = event.target;
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 200) {
    isLazyLoading.value = true;
    setTimeout(() => {
      if (mapSearchQuery.value) {
        loadMoreFiltered();
      } else {
        actorRoleMapperStore.loadMore();
      }
      isLazyLoading.value = false;
    }, 500); // 模拟网络延迟，让加载动画可见
  }
}, 200);

const isGithubConfigured = computed(() => {
  return !!configStore.appConfig.episode_refresher_config?.github_config?.repo_url;
});

const isTaskRunning = (keyword) => {
  return taskStore.tasks.some(t => t.name.includes('演员角色映射') && t.name.includes(keyword) && t.status === 'running');
};

const filteredMap = ref([]);
const filteredFullList = ref([]);
const itemsPerFilterLoad = 30;

// --- 新增：计算属性，判断当前视图是否已全部加载 ---
const isFullyLoadedForCurrentView = computed(() => {
  if (mapSearchQuery.value) {
    return filteredMap.value.length >= filteredFullList.value.length;
  }
  return isFullyLoaded.value;
});

watch(mapSearchQuery, _.debounce((query) => {
  if (!query) {
    // --- 核心修改：当搜索清空时，从 store 中获取当前已展示的数据 ---
    // 这样可以保持与懒加载状态的同步
    filteredMap.value = displayedActorMap.value;
    // --- 修改结束 ---
    return;
  }
  const lowerQuery = query.toLowerCase();
  filteredFullList.value = fullActorMap.value.filter(item => {
    const titleMatch = item.title.toLowerCase().includes(lowerQuery);
    if (titleMatch) return true;
    const actorMatch = Object.keys(item.map).some(name => name.toLowerCase().includes(lowerQuery));
    return actorMatch;
  });
  filteredMap.value = filteredFullList.value.slice(0, itemsPerFilterLoad);
}, 300));

function loadMoreFiltered() {
  if (filteredMap.value.length >= filteredFullList.value.length) return;
  const currentLength = filteredMap.value.length;
  const nextItems = filteredFullList.value.slice(currentLength, currentLength + itemsPerFilterLoad);
  filteredMap.value.push(...nextItems);
}

watch(() => mapSearchQuery.value === '', (isCleared) => {
  if (isCleared) {
    filteredMap.value = displayedActorMap.value;
  }
});

// --- 修改：当 store 中的 displayedActorMap 变化时，同步更新 filteredMap ---
watch(displayedActorMap, (newVal) => {
  if (!mapSearchQuery.value) {
    filteredMap.value = newVal;
  }
}, { deep: true });


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
  actorRoleMapperStore.fetchMap().then(() => {
    filteredMap.value = displayedActorMap.value;
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

async function startTask(endpoint, payload, confirmOptions) {
  try {
    if (confirmOptions) {
      await ElMessageBox.confirm(confirmOptions.message, confirmOptions.title, {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info',
      });
    }
    await actorRoleMapperStore.startTask(endpoint, payload);
  } catch (error) {
    // User cancelled
  }
}

const handleGenerate = () => {
  const payload = { 
    scope: scope.value,
    actor_limit: actorLimit.value,
    generation_mode: generationMode.value
  };
  
  let confirmTitle = '确认生成映射表';
  let confirmMessage = '';

  if (generationMode.value === 'overwrite') {
    confirmTitle = '确认生成映射表 (覆盖模式)';
    confirmMessage = `即将以【覆盖模式】扫描媒体库并生成映射表，此操作会完全替换本地已有的 \`actor_role_map.json\` 文件。是否继续？`;
  } else if (generationMode.value === 'incremental') {
    confirmTitle = '确认生成映射表 (增量模式)';
    confirmMessage = `即将以【增量模式】扫描媒体库，仅将新发现的作品追加到映射表中，不会影响已有记录。是否继续？`;
  } else if (generationMode.value === 'update_selected') {
    // --- 修改：移除范围检查，更新提示文本 ---
    confirmTitle = '确认生成映射表 (更新范围内模式)';
    confirmMessage = `即将强制更新您在“通用目标范围”中选择的所有媒体项的映射关系，其他已有数据将保留不变。此操作适合修正特定范围内的错误数据。是否继续？`;
    // --- 修改结束 ---
  }

  startTask('/api/actor-role-mapper/generate', payload, {
    message: confirmMessage,
    title: confirmTitle
  }).then(() => {
    // 任务启动后，延迟一段时间再刷新列表，给后端一点处理时间
    setTimeout(() => {
      actorRoleMapperStore.fetchMap();
    }, 2000);
  });
};

const handleUpload = () => {
  startTask('/api/actor-role-mapper/upload', {}, {
    message: '即将把本地的 `actor_role_map.json` 文件上传到 GitHub，这会覆盖远程仓库中的同名文件。是否继续？',
    title: '确认上传'
  });
};

const handleDownload = () => {
  startTask('/api/actor-role-mapper/download', {}, {
    message: '即将从 GitHub 下载映射表，并覆盖本地的 `actor_role_map.json` 文件。请确保您已保存本地的未同步更改。是否继续？',
    title: '确认下载'
  }).then(() => actorRoleMapperStore.fetchMap());
};

const handleRestore = () => {
  startTask('/api/actor-role-mapper/restore', { scope: scope.value }, {
    message: '即将根据本地的 `actor_role_map.json` 文件和当前选择的范围，恢复 Emby 中的演员角色名。此操作会直接修改您的 Emby 数据。是否继续？',
    title: '确认恢复演员角色'
  });
};

const actions = ref([
  { 
    key: 'generate', 
    title: '1. 生成映射表', 
    description: '扫描 Emby 媒体库，在本地生成 `actor_role_map.json` 文件。', 
    icon: markRaw(DocumentAdd), 
    bgClass: 'bg-generate', 
    buttonText: '立即生成',
    taskKeyword: '生成',
    handler: handleGenerate 
  },
  { 
    key: 'upload', 
    title: '2. 上传到 GitHub', 
    description: '将本地的映射表备份到云端 GitHub 仓库。', 
    icon: markRaw(Upload), 
    bgClass: 'bg-upload', 
    buttonText: '立即上传',
    taskKeyword: '上传',
    handler: handleUpload,
    disabled: () => !isGithubConfigured.value
  },
  { 
    key: 'download', 
    title: '3. 从 GitHub 下载', 
    description: '从云端仓库取回映射表，覆盖本地文件。', 
    icon: markRaw(Download), 
    bgClass: 'bg-download', 
    buttonText: '立即下载',
    taskKeyword: '下载',
    handler: handleDownload,
    disabled: () => !isGithubConfigured.value
  },
  { 
    key: 'restore', 
    title: '4. 恢复演员角色', 
    description: '使用本地映射表，智能修正 Emby 中的角色名。', 
    icon: markRaw(MagicStick), 
    bgClass: 'bg-restore', 
    buttonText: '开始恢复',
    taskKeyword: '恢复',
    handler: handleRestore 
  }
]);

const handleCollapseChange = (activeNames) => {
  if (!activeNames || activeNames.length === 0) return;
  const newActiveId = activeNames[activeNames.length - 1];
  if (newActiveId && !actorAvatarsCache[newActiveId]) {
    fetchAvatars(newActiveId);
  }
};


const fetchAvatars = async (tmdbId) => {
  // 初始化缓存，防止重复请求
  actorAvatarsCache[tmdbId] = {}; 
  
  try {
    // --- 核心修改：调用新的后端接口 ---
    const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/avatars/${tmdbId}`);
    if (!response.ok) {
      // 如果接口返回404或500等，静默失败，不在UI上报错
      console.error(`获取 TMDB ID ${tmdbId} 的演员头像信息失败`);
      return;
    }
    
    const actorsData = await response.json();
    if (!actorsData || actorsData.length === 0) {
      return; // 没有找到演员或头像信息
    }

    const avatarMap = {};
    const apiKey = configStore.appConfig.server_config.api_key;
    
    actorsData.forEach(actor => {
      if (actor.PrimaryImageTag) {
        const imagePath = `Items/${actor.Id}/Images/Primary?tag=${actor.PrimaryImageTag}&api_key=${apiKey}`;
        // 使用 encodeURIComponent 确保 URL 安全
        avatarMap[actor.Name] = `${API_BASE_URL}/api/emby-image-proxy?path=${encodeURIComponent(imagePath)}`;
      } else {
        avatarMap[actor.Name] = ''; // 保持无头像的为空字符串
      }
    });
    
    actorAvatarsCache[tmdbId] = avatarMap;

  } catch (error) {
    // 网络层面的错误，也静默处理
    console.error(`获取 TMDB ID ${tmdbId} 的演员头像时发生网络错误:`, error);
  }
};

const getActorAvatar = (tmdbId, actorName) => {
  const cache = actorAvatarsCache[tmdbId];
  return cache ? cache[actorName] || '' : '';
};

const handleSingleRestore = (item) => {
  actorRoleMapperStore.startSingleRestore(item);
};
const handleSaveItem = (item) => {
  actorRoleMapperStore.saveMapChanges(item);
};
</script>

<style scoped>
.actor-role-mapper-page {
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
.header-left {
  flex-shrink: 1;
}
.header-right {
  flex-shrink: 0;
  max-width: 500px;
  margin-right: 60px;
}
.github-warning-alert {
  padding: 8px 12px;
}
.github-warning-alert p {
  margin: 0;
  line-height: 1.6;
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
.save-scope-button-container {
  margin-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 20px;
}
.save-scope-button-container .el-button {
  width: 100%;
}

.action-center {
  flex-shrink: 0;
}
.action-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 15px;
}
.action-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.action-icon-wrapper {
  width: 23px;
  height: 23px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.action-icon-wrapper .el-icon {
  font-size: 15px;
  color: white;
}
.bg-generate { background-color: #409EFF; }
.bg-upload { background-color: #67C23A; }
.bg-download { background-color: #E6A23C; }
.bg-restore { background-color: #F56C6C; }

.action-title-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.action-title-wrapper h4 {
  margin: 0;
  font-size: 0.9rem;
}
.help-icon {
  color: var(--el-text-color-secondary);
  cursor: pointer;
}

.map-preview {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.map-preview > :deep(.el-card__body) {
  flex-grow: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 0;
}
.preview-toolbar {
  display: flex;
  gap: 10px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.map-list-container {
  flex-grow: 1;
  overflow-y: auto;
}
.map-list-container .el-collapse {
  border-top: none;
  border-bottom: none;
}
.map-list-container :deep(.el-collapse-item__header) {
  padding: 0 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  width: 100%;
  box-sizing: border-box;
}
.map-list-container :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}
.map-list-container :deep(.el-collapse-item__content) {
  padding: 10px 20px;
}
.collapse-title {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.collapse-title-container {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  margin-right: 10px;
}
.restore-button {
  margin-left: auto;
  flex-shrink: 0;
}

.actor-list {
  padding: 0 10px;
}
.actor-item {
  display: flex;
  align-items: center;
  gap: 15px;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-extra-light);
}
.actor-item .el-avatar {
  width: 98px;
  height: 148px;
  flex-shrink: 0;
  border-radius: 4px;
}
.actor-item .el-avatar :deep(img) {
  object-fit: cover;
}

.actor-item:last-child {
  border-bottom: none;
}
.actor-name {
  width: 150px;
  font-weight: bold;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.actor-role {
  flex-grow: 1;
  color: var(--el-text-color-secondary);
}
.actor-tmdb-id {
  flex-shrink: 0;
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
.actor-list-toolbar {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-bottom: 10px;
  padding: 0 10px;
}
.toolbar-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.actor-role-input {
  flex-grow: 1;
}
.actor-role-input :deep(.el-input__wrapper) {
  box-shadow: none;
  background-color: transparent;
}
.actor-role-input :deep(.el-input__wrapper:hover) {
  background-color: var(--el-fill-color-light);
}
.actor-role-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--el-color-primary) inset;
}
/* --- 新增：设置按钮样式 --- */
.settings-button {
  margin-left: auto;
  color: var(--el-text-color-secondary);
}
.settings-popover .el-form-item {
  margin-bottom: 0;
}
.settings-popover .form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
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