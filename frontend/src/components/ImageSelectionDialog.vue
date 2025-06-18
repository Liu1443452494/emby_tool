<template>
  <el-dialog
    :model-value="visible"
    :title="`请为《${mediaName}》选择一张${imageTypeLabel}`"
    width="90%"
    top="5vh"
    :before-close="() => $emit('update:visible', false)"
    class="image-selection-dialog"
  >
    <div 
      class="gallery-container" 
      :class="{ 'single-row-mode': isSingleRowMode }"
      ref="galleryContainerRef"
    >
      <div 
        v-for="(image, index) in images" 
        :key="image.file_path"
        class="image-card"
        :class="{ 
          selected: selectedImage?.file_path === image.file_path,
          'poster-type': imageType === 'poster',
          'backdrop-type': imageType === 'backdrop' || imageType === 'logo'
        }"
        @click="selectedImage = image"
        :ref="el => { if (el) imageCardRefs[index] = el }"
      >
        <div v-if="image.source" class="source-badge" :class="`source-${image.source}`">
          {{ image.source === 'douban' ? '豆瓣' : 'TMDB' }}
        </div>

        <el-image 
          :src="imageSources[index]" 
          :alt="`Image ${index}`" 
          :fit="imageType === 'logo' ? 'contain' : 'cover'" 
          class="gallery-image"
          :class="{ 'logo-image-style': imageType === 'logo' }"
        >
          <template #placeholder>
            <div class="image-placeholder"><el-icon class="is-loading"><Loading /></el-icon></div>
          </template>
          <template #error>
            <div class="image-placeholder">
              <span>加载失败</span>
            </div>
          </template>
        </el-image>
        <div class="image-overlay">
          <div class="image-info">
            <el-icon><StarFilled /></el-icon>
            <span>{{ image.vote_average.toFixed(1) }}</span>
          </div>
          <div v-if="image.iso_639_1" class="image-lang">{{ image.iso_639_1.toUpperCase() }}</div>
        </div>
        <div v-if="selectedImage?.file_path === image.file_path" class="selected-indicator">
          <el-icon><Select /></el-icon>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="() => $emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="handleConfirm" :disabled="!selectedImage">确认更换</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch, onBeforeUpdate, nextTick } from 'vue';
import { useIntersectionObserver } from '@vueuse/core';
import { StarFilled, Loading, Select } from '@element-plus/icons-vue';
import { API_BASE_URL, TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';

const props = defineProps({
  visible: Boolean,
  images: { type: Array, default: () => [] },
  mediaName: { type: String, default: '' },
  imageType: { type: String, default: 'poster' },
});
const emit = defineEmits(['update:visible', 'confirm']);

const imageTypeLabel = computed(() => {
  const labels = { poster: '海报', backdrop: '背景图', logo: 'Logo' };
  return labels[props.imageType] || '图片';
});

const selectedImage = ref(null);
const imageCardRefs = ref([]);
const imageSources = ref([]);

const galleryContainerRef = ref(null);
const isSingleRowMode = ref(false);
const CARD_MIN_WIDTH = 250;
const GAP = 20;

const updateLayoutMode = () => {
  nextTick(() => {
    if (!galleryContainerRef.value || props.images.length === 0) {
      isSingleRowMode.value = false;
      return;
    }
    
    const containerWidth = galleryContainerRef.value.clientWidth;
    const maxCardsPerRow = Math.floor((containerWidth + GAP) / (CARD_MIN_WIDTH + GAP));
    
    if (props.images.length <= maxCardsPerRow) {
      isSingleRowMode.value = true;
    } else {
      isSingleRowMode.value = false;
    }
  });
};

onBeforeUpdate(() => {
  imageCardRefs.value = [];
});

watch(() => props.images, () => {
  if (props.images && props.images.length > 0) {
    imageSources.value = new Array(props.images.length).fill('');
    selectedImage.value = null;
    updateLayoutMode();
  }
}, { immediate: true, deep: true });

// --- 核心修改：使用 nextTick 替代 setTimeout ---
watch(() => props.visible, (newVal) => {
  if (newVal) {
    updateLayoutMode();
    
    nextTick(() => {
      imageCardRefs.value.forEach((card, index) => {
        if (!card) return; // 增加一个安全检查
        useIntersectionObserver(card, ([{ isIntersecting }]) => {
          if (isIntersecting && !imageSources.value[index]) {
            const currentImage = props.images[index];
            let imageUrl = '';
            if (currentImage.source === 'douban') {
              imageUrl = `${API_BASE_URL}/api/gallery/proxy-image?image_url=${encodeURIComponent(currentImage.file_path)}`;
            } else {
              const imageSize = TMDB_IMAGE_SIZES.poster;
              imageUrl = `${TMDB_IMAGE_BASE_URL}${imageSize}${currentImage.file_path}`;
            }
            imageSources.value[index] = imageUrl;
          }
        }, { root: galleryContainerRef.value });
      });
    });
  }
});

const handleConfirm = () => {
  if (selectedImage.value) {
    emit('confirm', selectedImage.value);
  }
};
</script>

<style>
.image-selection-dialog .el-dialog__body {
  height: 75vh;
  padding: 10px 20px;
}
</style>

<style scoped>
.gallery-container {
  display: grid;
  height: 100%;
  overflow-y: auto;
  padding: 5px;
  gap: 20px;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  grid-auto-rows: min-content;
  align-content: flex-start;
}

.gallery-container.single-row-mode {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  gap: 20px;
}

.image-card {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  border: 2px solid transparent;
  background-color: var(--el-fill-color-light);
}

.single-row-mode .image-card {
  width: auto;
  height: auto;
  max-height: 95%;
  max-width: 95%;
  flex-shrink: 1;
}

.image-card.poster-type {
  aspect-ratio: 2 / 3;
}
.image-card.backdrop-type {
  aspect-ratio: 16 / 9;
}

.image-card:hover {
  transform: scale(1.03);
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}
.image-card.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 3px var(--el-color-primary-light-5);
}
.gallery-image {
  width: 100%;
  height: 100%;
  display: block;
}
.image-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: var(--el-text-color-secondary);
}
.image-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 8px;
  background: linear-gradient(to top, rgba(0,0,0,0.7) 0%, transparent 100%);
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.image-info {
  display: flex;
  align-items: center;
  gap: 4px;
}
.image-lang {
  background-color: rgba(0,0,0,0.5);
  padding: 2px 5px;
  border-radius: 4px;
}
.selected-indicator {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background-color: var(--el-color-primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.logo-image-style {
  padding: 10px;
  box-sizing: border-box;
}

.source-badge {
  position: absolute;
  top: 0;
  left: 0;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: bold;
  color: #fff;
  border-bottom-right-radius: 8px;
  z-index: 1;
  text-shadow: 1px 1px 2px rgba(0,0,0,0.5);
}
.source-douban {
  background-color: rgba(0, 119, 34, 0.8);
}
.source-tmdb {
  background-color: rgba(1, 180, 228, 0.8);
}
</style>