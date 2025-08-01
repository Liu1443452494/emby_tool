
<template>
  <div
    class="results-container energy-ring-loading-container"
    v-loading="props.loading"
    element-loading-text="正在获取上映列表..."
    element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
  >
    <div v-if="props.items && props.items.length > 0" class="results-grid">
      <div v-for="item in props.items" :key="item.tmdb_id" class="media-card">
        <div class="card-background"></div>
        
        <div class="image-container">
          <el-image :src="getPosterUrl(item.poster_path)" fit="cover" class="poster-image" lazy>
            <template #placeholder><div class="image-slot-placeholder"></div></template>
            <template #error>
              <div class="image-slot-error">
                <el-icon><Picture /></el-icon>
              </div>
            </template>
          </el-image>
          
          <div class="badge top-left">{{ item.media_type === 'movie' ? '电影' : '剧集' }}</div>
          <div class="badge top-right">{{ item.release_date }}</div>

          <div class="card-actions">
            <div 
              class="action-button permanent-button"
              :class="{ 'is-permanent': item.is_permanent }"
              @click.stop="$emit('permanent-toggle', item)"
              title="永久收藏"
            >
              <el-icon>
                <StarFilled v-if="item.is_permanent" />
                <Star v-else />
              </el-icon>
            </div>
            <div 
              class="action-button ignore-button"
              @click.stop="$emit('ignore', item)"
              title="不感兴趣"
            >
              <el-icon><View /></el-icon>
            </div>
            <div 
              class="action-button subscribe-button" 
              :class="{ 'subscribed': isSubscribed(item) }"
              @click.stop="toggleSubscription(item)"
              title="订阅"
            >
              <svg class="heart-icon" viewBox="0 0 24 24">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
              </svg>
            </div>
          </div>
        </div>

        <div class="card-content">
          <div class="title-wrapper">
            <h4 class="title" :title="item.title">{{ item.title }}</h4>
            <!-- --- 核心修改：将 span 改为 a 标签 --- -->
            <a
              :href="`https://www.themoviedb.org/${item.media_type === 'tv' ? 'tv' : 'movie'}/${item.tmdb_id}`"
              target="_blank"
              rel="noopener noreferrer"
              class="tmdb-id"
              title="在 TMDB 中查看详情"
              @click.stop
            >
              ID: {{ item.tmdb_id }}
            </a>
            <!-- --- 修改结束 --- -->
          </div>
          <!-- --- 新增：地区和类型 --- -->
          <p class="info-line">
            <span class="info-label">地区:</span>
            <span class="info-value">{{ getCountryNames(item.origin_country) }}</span>
          </p>
          <p class="info-line">
            <span class="info-label">类型:</span>
            <span class="info-value">{{ getGenreNames(item.genres) }}</span>
          </p>
          <p v-if="item.actors && item.actors.length > 0" class="info-line">
            <span class="info-label">主演:</span>
            <span class="info-value">{{ item.actors.join(' / ') }}</span>
          </p>
          <!-- --- 新增结束 --- -->
        </div>
      </div>
    </div>
    <el-empty v-else :description="props.type === 'subscription' ? '您还没有订阅任何即将上映的影视剧' : '在当前筛选条件下，未找到即将上映的影视剧'" />
  </div>
</template>

<script setup>
import { defineProps, defineEmits } from 'vue';
import { useUpcomingStore } from '@/stores/upcoming';
import { API_BASE_URL, TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';
import { COUNTRY_MAP } from '@/config/filterConstants';
import { Picture, Star, StarFilled, View } from '@element-plus/icons-vue';

const props = defineProps(['items', 'loading', 'type']);
const emit = defineEmits(['subscribe', 'unsubscribe', 'permanent-toggle', 'ignore']);

const store = useUpcomingStore();
const getCountryNames = (codes) => {
  if (!codes || codes.length === 0) return '未知';
  return codes.map(code => COUNTRY_MAP[code.toLowerCase()] || code).join(' / ');
};

const getGenreNames = (genres) => {
  if (!genres || genres.length === 0) return '未知';
  return genres.join(' / ');
};

const getActorNames = (actors) => {
  if (!actors || actors.length === 0) return '暂无';
  return actors.join(' / ');
};

const getPosterUrl = (path) => {
  if (!path) return '';
  const fullUrl = `${TMDB_IMAGE_BASE_URL}${TMDB_IMAGE_SIZES.poster}${path}`;
  // --- 核心修改：返回代理 URL ---
  return `${API_BASE_URL}/api/image-proxy?url=${encodeURIComponent(fullUrl)}`;
};
const isSubscribed = (item) => item.is_subscribed;

const toggleSubscription = (item) => {
  // --- 核心修改：直接使用 is_subscribed 字段判断 ---
  if (item.is_subscribed) {
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

.image-container {
  position: relative; /* 为按钮和角标提供定位上下文 */
  z-index: 2;
  width: 100%;
  aspect-ratio: 2 / 3;
  flex-shrink: 0;
  overflow: hidden; /* 确保角标不会超出图片范围 */
}
.badge {
  position: absolute;
  z-index: 4;
  padding: 4px 6px;
  font-size: 12px;
  font-weight: bold;
  color: white;
  background-color: rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(10px);
  border-radius: 15px;
  
}
.badge.top-left {
  top: 0px;
  left: 0px;
  background-color: rgba(31, 14, 213, 0.5);
}
.badge.top-right {
  top: 0px;
  right: 4px;
}

.poster-image {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: transparent;
}

.card-actions {
  position: absolute;
  bottom: 10px;
  right: 10px;
  z-index: 3;
  display: flex;
  gap: 10px;
  opacity: 0;
  transform: scale(0.8) translateY(10px);
  transition: all 0.3s ease;
}

.media-card:hover .card-actions {
  opacity: 1;
  transform: scale(1) translateY(0);
}

.action-button {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease;
  backdrop-filter: blur(5px);
}

.action-button:hover {
  transform: scale(1.1);
  background-color: rgba(0, 0, 0, 0.7);
}

.permanent-button {
  font-size: 20px;
  color: #e6a23c;
}
.permanent-button.is-permanent {
  color: #f7ba2a;
  background-color: rgba(247, 186, 42, 0.2);
}

.ignore-button {
  font-size: 20px;
  color: #909399;
}
.ignore-button:hover {
  color: #c8c9cc;
}

.subscribe-button .heart-icon {
  width: 20px;
  height: 20px;
  transition: all 0.3s ease;
  stroke: #fff;
  stroke-width: 2;
  fill: none;
}
.subscribe-button.subscribed {
  background-color: rgba(245, 108, 108, 0.2);
}
.subscribe-button.subscribed .heart-icon {
  fill: #f56c6c;
  stroke: #f56c6c;
}
/* --- 修改结束 --- */

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
  justify-content: center; /* 垂直居中 */
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
  font-weight: 700;
  flex-shrink: 0; /* 防止ID被压缩 */
  
  text-decoration: none;
}
.tmdb-id:hover {
  color: #85ce61;
  transform: scale(1.08);
}

.info-line {
  margin: 2px 0 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.info-label {
  font-weight: bold;
  margin-right: 5px;
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