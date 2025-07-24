<template>
  <div class="card-aspect-ratio-container">
    <el-card 
      class="chasing-card" 
      shadow="always" 
      :body-style="{ 
        padding: '0px', 
        height: '100%', 
        display: 'flex', 
        alignItems: 'center', /* 垂直居中 wrapper */
        justifyContent: 'center', /* 水平居中 wrapper */
        boxSizing: 'border-box'
      }"
      :style="{ '--backdrop-image-url': `url(${backdropUrl})` }"
    >
      <div class="content-wrapper">
        <!-- 左侧海报 -->
        <div class="poster-section">
          <el-image :src="posterUrl" fit="cover" class="series-poster" lazy>
            <template #error>
              <div class="image-slot">
                <el-icon><Picture /></el-icon>
              </div>
            </template>
          </el-image>
        </div>

        <!-- 右侧信息 -->
        <div class="info-section">
          <h4 class="series-title">{{ series.name }}</h4>
          <div class="meta-info">
            <span>{{ series.year }}</span>
            <el-divider direction="vertical" />
            <span>首播: {{ series.tmdb_first_air_date || 'N/A' }}</span>
          </div>
          <div class="progress-info">
            <span class="progress-label">入库进度:</span>
            <div class="progress-bar-container">
              <el-progress
                :percentage="progressPercentage"
                :stroke-width="8"
                striped
                striped-flow
                :show-text="false"
                color="#67c23a"
              />
            </div>
            <span class="progress-text">
              {{ series.emby_episode_count }} / {{ series.tmdb_total_episodes || '?' }}
            </span>
          </div>
          <div class="status-info">
            <span class="status-label">TMDB 状态:</span>
            <el-tag :type="statusTagType" size="small" effect="light">{{ statusText }}</el-tag>
          </div>
        </div>
      </div>

      <!-- 右上角操作菜单 -->
      <el-dropdown class="more-options-menu" trigger="click" @command="handleCommand">
        <span class="el-dropdown-link">
          <el-icon><MoreFilled /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="remove" :icon="Delete">
              移除追更
            </el-dropdown-item>
            <el-dropdown-item command="calendar" :icon="Calendar" disabled>
              查看日历
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-card>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import { useMediaStore } from '@/stores/media';
import { MoreFilled, Delete, Calendar, Picture } from '@element-plus/icons-vue';

const props = defineProps({
  series: {
    type: Object,
    required: true,
  },
});

const emit = defineEmits(['remove']);

const mediaStore = useMediaStore();
const serverUrl = computed(() => mediaStore.appConfig?.server_config?.server);
const apiKey = computed(() => mediaStore.appConfig?.server_config?.api_key);

const posterUrl = computed(() => {
  if (!props.series.emby_id || !serverUrl.value || !apiKey.value) return '';
  return `${serverUrl.value}/Items/${props.series.emby_id}/Images/Primary?api_key=${apiKey.value}&fillWidth=200&quality=90`;
});

const backdropUrl = computed(() => {
  if (!props.series.emby_id || !serverUrl.value || !apiKey.value || !props.series.image_tags?.Backdrop) return '';
  return `${serverUrl.value}/Items/${props.series.emby_id}/Images/Backdrop/0?api_key=${apiKey.value}&maxWidth=800&tag=${props.series.image_tags.Backdrop}&quality=80`;
});

const progressPercentage = computed(() => {
  if (!props.series.tmdb_total_episodes || props.series.tmdb_total_episodes === 0) {
    return 0;
  }
  return Math.round((props.series.emby_episode_count / props.series.tmdb_total_episodes) * 100);
});

const statusMap = {
  'Returning Series': { text: '追更中', type: 'success' },
  'In Production': { text: '制作中', type: 'primary' },
  'Ended': { text: '已完结', type: 'info' },
  'Canceled': { text: '已砍', type: 'danger' },
  'Pilot': { text: '试播', type: 'warning' },
};

const statusText = computed(() => {
  return statusMap[props.series.tmdb_status]?.text || props.series.tmdb_status || '未知';
});

const statusTagType = computed(() => {
  return statusMap[props.series.tmdb_status]?.type || 'info';
});

const handleCommand = (command) => {
  if (command === 'remove') {
    emit('remove', props.series);
  }
};
</script>

<style scoped>
.card-aspect-ratio-container {
  width: 100%;
  aspect-ratio: 16 / 9;
  min-width: 400px;
}

.chasing-card {
  width: 100%;
  height: 100%;
  border-radius: 15px;
  overflow: hidden;
  position: relative;
  color: #fff;
  border: none;
}

.chasing-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-image: var(--backdrop-image-url);
  background-size: cover;
  background-position: center;
  filter: brightness(0.6);
  transform: scale(1.05);
  transition: transform 0.3s ease;
  z-index: 0;
}
.chasing-card:hover::before {
  transform: scale(1.1);
}

.chasing-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(to right, 
    rgba(0, 0, 0, 0.7) 0%, 
    rgba(0, 0, 0, 0.5) 50%, 
    rgba(0, 0, 0, 0.2) 100%
  );
  z-index: 0;
}

.chasing-card :deep(.el-card__body) {
  position: relative;
  z-index: 1;
  background-color: transparent;
}

/* 新增：内容包裹层 */
.content-wrapper {
  display: flex;
  align-items: flex-start; /* 关键：实现顶部对齐 */
  gap: 20px;
  width: 100%;
  padding: 0 20px; /* 内边距移到这里 */
  box-sizing: border-box;
}

.poster-section {
  width: 30%;
  max-width: 130px;
  flex-shrink: 0;
}
.series-poster {
  width: 100%;
  aspect-ratio: 2 / 3;
  border-radius: 8px;
  background-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
}
.image-slot {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.5);
  font-size: 30px;
}

.info-section {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
  padding-top: 5px;
}

.series-title {
  margin: 0;
  font-size: 1.4rem;
  font-weight: bold;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #fff;
  text-shadow: 1px 1px 3px rgba(0,0,0,0.5);
}

.meta-info {
  font-size: 0.9rem;
  color: rgba(255, 255, 255, 0.8);
  display: flex;
  align-items: center;
}
.meta-info .el-divider {
  background-color: rgba(255, 255, 255, 0.3);
}

.progress-info, .status-info {
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 8px;
}
.progress-label, .status-label {
  color: rgba(255, 255, 255, 0.9);
  flex-shrink: 0;
}
.progress-bar-container {
  flex-grow: 1;
  max-width: 200px;
}
.progress-text {
  font-size: 0.9rem;
  color: rgba(255, 255, 255, 0.8);
}
.info-section :deep(.el-progress__bar) {
  background-color: rgba(255, 255, 255, 0.2);
}

.more-options-menu {
  position: absolute;
  top: 15px;
  right: 15px;
  cursor: pointer;
  color: rgba(255, 255, 255, 0.7);
  font-size: 1.2rem;
  transition: all 0.2s;
  z-index: 2;
}
.more-options-menu:hover {
  color: #fff;
}
.el-dropdown-link {
  outline: none;
  color: inherit;
}
</style>