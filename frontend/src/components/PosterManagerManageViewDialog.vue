<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="handleClose"
    :title="dialogTitle"
    width="auto"
    top="auto"
    class="poster-manager-manage-dialog"
    :close-on-click-modal="false"
    destroy-on-close
    @open="fetchDetails"
  >
    <div v-loading="isFetchingDetails" class="manage-view">
      <div class="manage-header">
        <el-link type="primary" :icon="ArrowLeft" @click="goBack">重新选择</el-link>
      </div>

    <!-- frontend/src/components/PosterManagerManageViewDialog.vue (template部分最终修正) -->

      <div class="comparison-area">
        <!-- 左侧：Emby -->
        <div class="side-panel">
          <div class="panel-header">Emby</div>
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
          <div class="panel-header">GitHub 备份</div>
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

const dialogTitle = computed(() => {
  return props.mediaItem ? `单体图片管理: ${props.mediaItem.Name} (${props.mediaItem.ProductionYear})` : '单体图片管理';
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

const handleEmbyAction = async (type) => {
  isFetchingDetails.value = true;
  const success = await store.backupSingleImage(props.mediaItem.Id, type);
  if (success) await fetchDetails();
  isFetchingDetails.value = false;
};

const handleGithubAction = async (type, action) => {
  isFetchingDetails.value = true;
  if (action === 'restore') {
    // 恢复逻辑待实现
  } else if (action === 'delete') {
    const success = await store.deleteSingleImage(props.mediaItem.Id, type);
    if (success) await fetchDetails();
  }
  isFetchingDetails.value = false;
};
</script>

/* frontend/src/components/PosterManagerManageViewDialog.vue (style块替换) */

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
  justify-content: flex-end;
  align-items: center;
  padding: 15px 30px;
  background-color: var(--el-fill-color-light);
  border-bottom: 1px solid var(--el-border-color);
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

/* --- 新增：为 Emby 侧的按钮应用朴素样式 --- */
.side-panel:first-of-type .image-layout :deep(.el-button) {
  --el-button-text-color: var(--el-text-color-regular);
  --el-button-bg-color: var(--el-fill-color);
  --el-button-border-color: var(--el-border-color-light);
  --el-button-hover-text-color: var(--el-color-primary);
  --el-button-hover-bg-color: var(--el-color-primary-light-9);
  --el-button-hover-border-color: var(--el-color-primary-light-7);
}
</style>