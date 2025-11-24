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
      <!-- 左侧：操作中心 -->
      <div class="left-panel">
        <el-card class="box-card action-center" shadow="never">
          <template #header>
            <div class="card-header">
              <span>操作中心</span>
            </div>
          </template>
          <div class="action-list">
            <div v-for="action in actions" :key="action.key" class="action-item">
              <div class="action-icon-wrapper" :class="action.bgClass"><el-icon><component :is="action.icon" /></el-icon></div>
              <div class="action-content">
                <div class="action-title-wrapper">
                  <h4>{{ action.title }}</h4>
                  <el-tooltip :content="action.description" placement="top" effect="dark">
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <p class="action-desc">{{ action.shortDesc }}</p>
                
                <!-- 冷却时间设置插槽 -->
                <div v-if="action.key === 'restore'" class="cooldown-setting">
                  <span>冷却(秒):</span>
                  <el-input-number 
                    v-model="batchCooldown" 
                    :min="0" 
                    :step="0.1" 
                    :precision="1"
                    size="small" 
                    style="width: 100px;"
                  />
                </div>
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
              <div class="header-with-count">
                <span>头像映射表预览</span>
                <el-tag v-if="avatarMapperStore.totalMapCount > 0" type="info" size="small" effect="plain">
                  共 {{ avatarMapperStore.totalMapCount }} 条
                </el-tag>
              </div>
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
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch, markRaw } from 'vue';
import { useRouter } from 'vue-router';
import { useConfigStore } from '@/stores/config';
import { useTaskStore } from '@/stores/task';
import { useActorAvatarMapperStore } from '@/stores/actorAvatarMapper';
import { storeToRefs } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Upload, Download, MagicStick, Search, QuestionFilled, User } from '@element-plus/icons-vue';
import { useStorage } from '@vueuse/core';
import _ from 'lodash';

const router = useRouter();

const configStore = useConfigStore();
const taskStore = useTaskStore();
const avatarMapperStore = useActorAvatarMapperStore();
const { displayedAvatarMap, isFullyLoaded } = storeToRefs(avatarMapperStore);

const mapSearchQuery = ref('');
const mapListContainerRef = ref(null);
const isLazyLoading = ref(false);

// 使用 useStorage 持久化冷却时间，默认 0.5 秒
const batchCooldown = useStorage('actor-avatar-mapper-cooldown', 0.5);

const handleScroll = _.throttle(({ scrollTop }) => {
  if (isLazyLoading.value) return;
  
  const container = mapListContainerRef.value;
  if (!container) return;
  
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

const filteredMap = ref([]);
const filteredFullList = ref([]);
const itemsPerFilterLoad = 10;

watch(mapSearchQuery, _.debounce((query) => {
  if (!query) {
    filteredMap.value = displayedAvatarMap.value;
    return;
  }
  const lowerQuery = query.toLowerCase();
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

watch(() => mapSearchQuery.value === '', (isCleared) => {
  if (isCleared) {
    filteredMap.value = displayedAvatarMap.value;
  }
});

watch(displayedAvatarMap, (newVal) => {
  if (!mapSearchQuery.value) {
    filteredMap.value = newVal;
  }
}, { deep: true });

onMounted(() => {
  avatarMapperStore.fetchMap().then(() => {
    filteredMap.value = displayedAvatarMap.value;
  });
});

const navigateToRefresherConfig = () => {
  router.push('/scheduled-tasks');
  ElMessage.info('已跳转，请找到“剧集元数据刷新”任务卡片并点击设置按钮。');
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
  avatarMapperStore.startTask('/api/actor-avatar-mapper/restore', { cooldown: batchCooldown.value }, {
    message: `即将根据本地的 actor_avatar_map.json 文件，批量恢复 Emby 中的演员头像。\n\n当前设置的冷却时间为：${batchCooldown.value} 秒/个。\n\n此操作会先拉取 Emby 全量演员数据建立索引，速度极快。是否继续？`,
    title: '确认批量恢复'
  });
};

const handleSingleRestore = (actorInfo) => {
  avatarMapperStore.startSingleRestore(actorInfo);
};

const actions = ref([
  { 
    key: 'upload', 
    title: '1. 上传到 GitHub', 
    shortDesc: '备份本地映射表到云端',
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
    shortDesc: '从云端覆盖本地映射表',
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
    shortDesc: '极速模式，无需扫描',
    description: '使用本地映射表，批量恢复 Emby 中的演员头像。采用全量索引技术，速度极快。', 
    icon: markRaw(MagicStick), 
    bgClass: 'bg-restore', 
    buttonText: '开始批量恢复',
    taskKeyword: '批量恢复',
    handler: handleRestore 
  }
]);
</script>

<style scoped>
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
  grid-template-columns: 320px 1fr; /* 调整左侧宽度 */
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
.action-center { flex-shrink: 0; }
.action-list { display: flex; flex-direction: column; gap: 15px; }

.action-item { 
  border: 1px solid var(--el-border-color); /* 加深边框颜色 */
  border-radius: 8px; 
  padding: 15px; 
  display: flex; 
  flex-direction: column; 
  gap: 12px; 
  background-color: var(--el-bg-color); /* 使用背景色而非填充色，增加对比 */
  box-shadow: var(--el-box-shadow-light); /* 增加轻微阴影 */
  transition: all 0.3s ease;
}
.action-item:hover {
  box-shadow: var(--el-box-shadow);
  border-color: var(--el-border-color-darker);
}

.action-icon-wrapper { 
  width: 32px; 
  height: 32px; 
  border-radius: 50%; 
  display: flex; 
  align-items: center; 
  justify-content: center; 
  align-self: flex-start;
}
.action-icon-wrapper .el-icon { font-size: 18px; color: white; }
.bg-upload { background-color: #67C23A; }
.bg-download { background-color: #E6A23C; }
.bg-restore { background-color: #F56C6C; }
.action-content { display: flex; flex-direction: column; gap: 4px; }
.action-title-wrapper { display: flex; align-items: center; gap: 8px; }
.action-title-wrapper h4 { margin: 0; font-size: 1rem; }
.action-desc { margin: 0; font-size: 12px; color: var(--el-text-color-secondary); }
.help-icon { color: var(--el-text-color-secondary); cursor: pointer; }

/* 针对按钮样式的增强 */
.action-item .el-button {
  width: 100%;
  border: 1px solid var(--el-border-color-darker); /* 强制显示边框 */
}
/* 深色模式下的按钮特殊处理 */
html.dark .action-item .el-button {
  background-color: var(--el-fill-color-light);
  border-color: var(--el-border-color-light);
}
html.dark .action-item .el-button:hover {
  background-color: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.map-preview { flex-grow: 1; display: flex; flex-direction: column; overflow: hidden; }
.map-preview > :deep(.el-card__body) { flex-grow: 1; overflow: hidden; display: flex; flex-direction: column; padding: 0; }
.preview-toolbar { display: flex; gap: 10px; padding: 10px 20px; border-bottom: 1px solid var(--el-border-color-lighter); }
.map-list-container {
  flex-grow: 1;
  overflow-y: auto;
}
.actor-avatar {
  width: 98px;
  height: 148px;
  flex-shrink: 0;
  border-radius: 4px;
}
.actor-avatar :deep(img) {
  object-fit: cover;
}
.header-with-count {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cooldown-setting {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  background-color: var(--el-fill-color-lighter);
  padding: 4px 8px;
  border-radius: 4px;
}
</style>