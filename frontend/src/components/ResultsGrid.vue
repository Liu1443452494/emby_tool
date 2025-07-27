<!-- frontend/src/components/ResultsGrid.vue (新文件) -->
<template>
  <div class="results-container" v-loading="props.loading">
    <div v-if="props.items && props.items.length > 0" class="results-grid">
      <div v-for="item in props.items" :key="item.tmdb_id" class="media-card">
        <div class="card-background"></div>
        
        <!-- --- 核心修改：新增图片容器 --- -->
        <div class="image-container">
          <el-image :src="getPosterUrl(item.poster_path)" fit="cover" class="poster-image" lazy>
            <template #placeholder><div class="image-slot-placeholder"></div></template>
            <template #error>
              <div class="image-slot-error">
                <el-icon><Picture /></el-icon>
              </div>
            </template>
          </el-image>
          
          <div 
            class="subscribe-button" 
            :class="{ 'subscribed': isSubscribed(item.tmdb_id) }"
            @click.stop="toggleSubscription(item)"
          >
            <svg class="heart-icon" viewBox="0 0 24 24">
              <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
            </svg>
          </div>
        </div>
        <!-- --- 修改结束 --- -->

        <div class="card-content">
          <div class="title-wrapper">
        <h4 class="title" :title="item.title">{{ item.title }}</h4>
        <span class="tmdb-id">ID:{{ item.tmdb_id }}</span>
      </div>
      <p class="release-date">首播日期：{{ item.release_date }}</p>
        </div>
      </div>
    </div>
    <el-empty v-else :description="props.type === 'subscription' ? '您还没有订阅任何即将上映的影视剧' : '在当前筛选条件下，未找到即将上映的影视剧'" />
  </div>
</template>

<script setup>
import { defineProps, defineEmits } from 'vue';
import { useUpcomingStore } from '@/stores/upcoming';
import { TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';
import { Picture } from '@element-plus/icons-vue';

const props = defineProps(['items', 'loading', 'type']);
const emit = defineEmits(['subscribe', 'unsubscribe']);

const store = useUpcomingStore();

const getPosterUrl = (path) => path ? `${TMDB_IMAGE_BASE_URL}${TMDB_IMAGE_SIZES.poster}${path}` : '';
const isSubscribed = (tmdbId) => tmdbId in store.subscriptions;

const toggleSubscription = (item) => {
  if (isSubscribed(item.tmdb_id)) {
    emit('unsubscribe', item);
  } else {
    emit('subscribe', item);
  }
};
</script>

<style scoped>
.results-container {
  min-height: 100%;
  padding: 20px;
}
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 25px;
}

.media-card {
  display: flex;
  flex-direction: column;
  border-radius: 15px;
  overflow: hidden;
  position: relative;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.media-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 15px 30px rgba(0, 0, 0, 0.3);
}

.card-background {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(135deg, #424242 0%, #212121 100%);
  z-index: 1;
}

/* --- 核心修改：新的图片容器和内部元素样式 --- */
.image-container {
  position: relative; /* 为按钮提供定位上下文 */
  z-index: 2;
  width: 100%;
  aspect-ratio: 2 / 3;
  flex-shrink: 0;
}

.poster-image {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: transparent;
}

.subscribe-button {
  position: absolute;
  bottom: 10px; /* 直接相对于图片容器定位 */
  right: 10px;
  z-index: 3; /* 确保在图片之上 */
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  cursor: pointer;
  transition: all 0.3s ease;
  backdrop-filter: blur(5px);
  opacity: 0;
  transform: scale(0.8);
}
/* --- 修改结束 --- */

.media-card:hover .subscribe-button {
  opacity: 1;
  transform: scale(1);
}

.image-slot-placeholder, .image-slot-error {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background-color: rgba(255, 255, 255, 0.05);
}
.image-slot-error {
  color: rgba(255, 255, 255, 0.3);
  font-size: 40px;
}

.card-content {
  position: relative;
  z-index: 2;
  padding: 12px;
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background-color: transparent;
  color: #fff;
}

.title-wrapper {
  display: flex;
  justify-content: space-between; /* 让标题和ID两端对齐 */
  align-items: baseline; /* 基线对齐 */
  gap: 8px;
  margin-bottom: 4px;
}

.title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #fff;
  text-align: left; /* 左对齐 */
  text-shadow: 1px 1px 3px rgba(0,0,0,0.7);
  flex-grow: 1; /* 允许标题伸展 */
}

.tmdb-id {
  font-size: 13px;
  color: #67c23a;
  font-weight: 900;
  flex-shrink: 0; /* 防止ID被压缩 */
  font-family: monospace;
}

.release-date {
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  text-align: left; /* 左对齐 */
  text-shadow: 1px 1px 2px rgba(0,0,0,0.5);
}

.heart-icon {
  width: 20px;
  height: 20px;
  transition: all 0.3s ease;
  stroke: #fff;
  stroke-width: 2;
  fill: none;
}

.subscribe-button.subscribed .heart-icon {
  fill: #f56c6c;
  stroke: #f56c6c;
}

.subscribe-button:hover .heart-icon {
  transform: scale(1.2);
}
</style>