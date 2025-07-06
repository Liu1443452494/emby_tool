<!-- frontend/src/components/PosterManagerManageViewDialog.vue (template块替换) -->
<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="handleClose"
    title="单个媒体图片管理"
    width="auto"
    top="auto"
    class="poster-manager-manage-dialog"
    :close-on-click-modal="false"
    destroy-on-close
    @open="fetchDetails"
  >
    <!-- 核心修改：添加 energy-ring-loading-container 类和加载文本 -->
    <div 
      v-loading="isFetchingDetails" 
      class="manage-view energy-ring-loading-container"
      element-loading-text="正在加载详情..."
    >
      <div class="manage-header">
        <h3 class="media-title">{{ mediaTitle }}</h3>
        <el-link type="primary" :icon="ArrowLeft" @click="goBack">重新选择媒体</el-link>
      </div>

      <div class="comparison-area">
        <!-- 左侧：Emby -->
        <div class="side-panel">
          <div class="panel-header">来自EMBY服务器</div>
          <div class="image-layout">
            <ImageCard
              class="poster-card"
              :image-info="embyImages.poster"
              type="poster"
              @action="handleEmbyAction('poster')"
              :action-text="getEmbyActionText('poster')"
              :action-disabled="isEmbyActionDisabled('poster')"
            />
            <div class="small-cards-column">
              <ImageCard
                class="small-card"
                :image-info="embyImages.fanart"
                type="fanart"
                @action="handleEmbyAction('fanart')"
                :action-text="getEmbyActionText('fanart')"
                :action-disabled="isEmbyActionDisabled('fanart')"
              />
              <ImageCard
                class="small-card"
                :image-info="embyImages.logo"
                type="logo"
                @action="handleEmbyAction('logo')"
                :action-text="getEmbyActionText('logo')"
                :action-disabled="isEmbyActionDisabled('logo')"
              />
            </div>
          </div>
        </div>

        <el-divider direction="vertical" class="main-divider" />

        <!-- 右侧：GitHub -->
        <div class="side-panel">
          <div class="panel-header">来自远程GitHub</div>
          <div class="image-layout">
            <ImageCard
              class="poster-card"
              :image-info="githubImages.poster"
              type="poster"
              :is-remote="true"
              @action="handleGithubAction('poster', 'restore')"
              @delete="handleGithubAction('poster', 'delete')"
            />
            <div class="small-cards-column">
              <ImageCard
                class="small-card"
                :image-info="githubImages.fanart"
                type="fanart"
                :is-remote="true"
                @action="handleGithubAction('fanart', 'restore')"
                @delete="handleGithubAction('fanart', 'delete')"
              />
              <ImageCard
                class="small-card"
                :image-info="githubImages.logo"
                type="logo"
                :is-remote="true"
                @action="handleGithubAction('logo', 'restore')"
                @delete="handleGithubAction('logo', 'delete')"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue';
import { usePosterManagerStore } from '@/stores/posterManager';
import { ArrowLeft } from '@element-plus/icons-vue';
import ImageCard from '@/components/ImageCard.vue';

const props = defineProps({
  visible: Boolean,
  mediaItem: { type: Object, default: null },
});
const emit = defineEmits(['update:visible', 'back-to-search']);

const store = usePosterManagerStore();
const isFetchingDetails = ref(false);
const embyImages = ref({});
const githubImages = ref({});

const mediaTitle = computed(() => {
  return props.mediaItem ? `${props.mediaItem.Name} (${props.mediaItem.ProductionYear})` : '加载中...';
});

const fetchDetails = async () => {
  if (!props.mediaItem) return;
  isFetchingDetails.value = true;
  const details = await store.fetchSingleItemDetails(props.mediaItem.Id);
  if (details) {
    embyImages.value = details.emby;
    githubImages.value = details.github;
  }
  isFetchingDetails.value = false;
};

const handleClose = () => {
  emit('update:visible', false);
};

const goBack = () => {
  handleClose();
  emit('back-to-search');
};

const getEmbyActionText = (type) => {
  if (!embyImages.value[type]) return '备份到 GitHub';
  if (githubImages.value[type]) {
    return store.config.overwrite_remote_files ? '覆盖远程备份' : '已存在备份';
  }
  return '备份到 GitHub';
};

const isEmbyActionDisabled = (type) => {
  if (!embyImages.value[type]) return true;
  return githubImages.value[type] && !store.config.overwrite_remote_files;
};

// frontend/src/components/PosterManagerManageViewDialog.vue (函数替换 1/2)

const handleEmbyAction = async (type) => {
  // 不再设置 loading 状态
  const success = await store.backupSingleImage(props.mediaItem.Id, type);
  // 如果 store action 返回 true (表示成功)，则刷新界面
  if (success) {
    isFetchingDetails.value = true; // 仅在刷新数据时显示loading
    await fetchDetails();
    isFetchingDetails.value = false;
  }
};

// frontend/src/components/PosterManagerManageViewDialog.vue (函数替换 2/2)

const handleGithubAction = async (type, action) => {
  if (action === 'restore') {
    // 恢复逻辑待实现
    ElMessage.info('此功能正在开发中...');
  } else if (action === 'delete') {
    const success = await store.deleteSingleImage(props.mediaItem.Id, type);
    if (success) {
      isFetchingDetails.value = true; // 仅在刷新数据时显示loading
      await fetchDetails();
      isFetchingDetails.value = false;
    }
  }
};
</script>


<style>
/* 非 scoped 样式，用于修改 el-dialog 根元素 */
.poster-manager-manage-dialog.el-dialog {
  width: fit-content;
  height: fit-content;
  max-width: 95vw;
  max-height: 95vh;
  margin: auto;
  display: flex;
  flex-direction: column;
}
.poster-manager-manage-dialog .el-dialog__body {
  padding: 0;
  flex-grow: 1;
  overflow: auto;
}
</style>

<style scoped>
.manage-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.manage-header {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 30px;
  background-color: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color);
}
.media-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 500;
}

.comparison-area {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 40px;
  padding: 25px 35px;
  width: 100%;
  box-sizing: border-box;
  overflow-x: auto;
}
.side-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 20px;
  min-width: 0;
}
.panel-header {
  text-align: center;
  font-size: 16px;
  font-weight: bold;
}
.main-divider {
  height: auto;
  align-self: stretch;
}
.image-layout {
  display: flex;
  align-items: center;
  gap: 20px;
}

.poster-card {
  width: min(333px, 48vw);
}

.small-cards-column {
  width: min(320px, 46vw);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.small-card {
  width: 100%;
}
</style>