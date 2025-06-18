<template>
  <el-dialog
    :model-value="visible"
    title="智能匹配结果确认"
    width="600px"
    :before-close="() => $emit('update:visible', false)"
  >
    <div v-if="candidate" class="confirm-content">
      <p>系统为您匹配到以下条目，请确认是否正确：</p>
      <div class="candidate-card">
        <el-image 
          :src="`https://image.tmdb.org/t/p/w185${candidate.poster_path}`" 
          fit="cover" 
          class="candidate-poster"
        >
          <template #error>
            <div class="poster-placeholder"><el-icon><PictureFilled /></el-icon></div>
          </template>
        </el-image>
        <div class="candidate-info">
          <h3 class="candidate-title">{{ candidate.title }}</h3>
          <p class="candidate-year">{{ candidate.release_date }}</p>
          <p class="candidate-overview">{{ candidate.overview }}</p>
        </div>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('reject')">否，让我手动选择</el-button>
      <el-button type="primary" @click="$emit('confirm', candidate.id)">是，获取图片</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { PictureFilled } from '@element-plus/icons-vue';

defineProps({
  visible: Boolean,
  candidate: { type: Object, default: null },
});
defineEmits(['update:visible', 'confirm', 'reject']);
</script>

<style scoped>
.confirm-content {
  line-height: 1.6;
}
.candidate-card {
  display: flex;
  gap: 20px;
  margin-top: 15px;
  padding: 15px;
  background-color: var(--el-fill-color-light);
  border-radius: 8px;
}
.candidate-poster {
  width: 120px;
  flex-shrink: 0;
  border-radius: 4px;
}
.candidate-info h3 {
  margin: 0 0 8px 0;
}
.candidate-info p {
  margin: 0 0 10px 0;
  font-size: 14px;
}
.candidate-year {
  color: var(--el-text-color-secondary);
}
.candidate-overview {
  max-height: 100px;
  overflow-y: auto;
  color: var(--el-text-color-regular);
}
</style>