<!-- 文件路径: frontend/src/components/DeletionReviewDialog.vue (新文件) -->
<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="审核待删除截图"
    width="85%"
    top="5vh"
    destroy-on-close
    @open="handleOpen"
  >
    <div v-loading="isLoading" class="review-dialog-content">
      <div class="review-toolbar">
        <div class="toolbar-left">
          <el-button @click="handleRefresh" :icon="Refresh" circle title="刷新列表" />
          <el-divider direction="vertical" />
          <el-button-group>
            <el-button @click="handleBatchSetState(true)">全部设为待删除</el-button>
            <el-button @click="handleBatchSetState(false)">全部设为保留</el-button>
          </el-button-group>
        </div>
        <div class="toolbar-right">
          <el-button type="primary" @click="handleSave" :loading="isSaving">保存修改</el-button>
        </div>
      </div>

      <div class="review-table-container">
        <el-table :data="reviewList" height="100%" row-key="log_item.github_path" border>
          <el-table-column type="expand" width="50">
            <template #default="props">
              <div class="expand-content">
                <div class="image-container">
                  <h4>Emby 当前图片 (官方图)</h4>
                  <el-image :src="props.row.emby_info?.image_url" fit="cover" lazy>
                    <template #error>
                      <div class="image-slot-error">无法加载Emby图片</div>
                    </template>
                  </el-image>
                </div>
                <div class="image-container">
                  <h4>待删除的 GitHub 截图</h4>
                  <el-image :src="props.row.github_info.image_url" fit="cover" lazy>
                     <!-- --- 新增代码块：加载状态占位符 --- -->
                     <template #placeholder>
                       <div class="image-slot-loading">
                         <el-icon class="is-loading"><Loading /></el-icon>
                       </div>
                     </template>
                     <!-- --- 结束新增 --- -->
                     <template #error>
                      <div class="image-slot-error">无法加载GitHub图片</div>
                    </template>
                  </el-image>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="剧集" prop="log_item.series_name" width="250" show-overflow-tooltip />
          <el-table-column label="分集" width="120">
            <template #default="scope">
              S{{ scope.row.log_item.episode_key.split('-')[0].padStart(2, '0') }}E{{ scope.row.log_item.episode_key.split('-')[1].padStart(2, '0') }}
            </template>
          </el-table-column>
          <el-table-column label="Emby 标题" prop="emby_info.title" show-overflow-tooltip>
             <template #default="scope">
              {{ scope.row.emby_info?.title || '无法获取Emby信息' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="150" align="center">
            <template #default="scope">
              <el-switch
                v-model="scope.row.log_item.pending_deletion"
                active-text="待删除"
                inactive-text="保留"
                inline-prompt
              />
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { Refresh, Loading } from '@element-plus/icons-vue';
import { API_BASE_URL } from '@/config/apiConfig';
import _ from 'lodash';

defineProps({
  visible: Boolean,
});
defineEmits(['update:visible']);

const isLoading = ref(false);
const isSaving = ref(false);
const reviewList = ref([]);

const handleOpen = async () => {
  await fetchReviewList();
};

const handleRefresh = async () => {
  await fetchReviewList();
  ElMessage.success('列表已刷新！');
};

const fetchReviewList = async () => {
  isLoading.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/github-delete-log`);
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || '获取审核列表失败');
    }
    const data = await response.json();
    reviewList.value = _.sortBy(data, ['log_item.series_name', 'log_item.episode_key']);
  } catch (error) {
    ElMessage.error(`获取失败: ${error.message}`);
  } finally {
    isLoading.value = false;
  }
};

const handleBatchSetState = (state) => {
  reviewList.value.forEach(item => {
    item.log_item.pending_deletion = state;
  });
};

const handleSave = async () => {
  isSaving.value = true;
  // 将前端的聚合数据结构转换回后端需要的原始日志结构
  const newLogData = {};
  reviewList.value.forEach(row => {
    const { tmdb_id, series_name, episode_key, ...restOfLogItem } = row.log_item;
    if (!newLogData[tmdb_id]) {
      newLogData[tmdb_id] = {
        series_name: series_name,
        emby_series_id: row.log_item.emby_series_id, // 确保 emby_series_id 也被正确处理
        episodes: {}
      };
    }
    // 提取分集特有信息
    const { emby_series_id, ...episodeSpecifics } = restOfLogItem;
    newLogData[tmdb_id].episodes[episode_key] = episodeSpecifics;
  });

  try {
    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/github-delete-log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newLogData),
    });
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || '保存失败');
    }
    ElMessage.success('审核状态已成功保存！');
  } catch (error) {
    ElMessage.error(`保存失败: ${error.message}`);
  } finally {
    isSaving.value = false;
  }
};
</script>

<style scoped>
.review-dialog-content {
  height: 75vh;
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.review-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 15px;
}
.review-table-container {
  flex-grow: 1;
  overflow: hidden;
}
.expand-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  padding: 20px;
  background-color: var(--el-fill-color-lighter);
}
.image-container {
  text-align: center;
}
.image-container h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
}
.image-container .el-image {
  width: 100%;
  aspect-ratio: 16 / 9; /* 强制16:9的宽高比 */
  height: auto; /* 高度自动，以适应宽度和比例 */
  background-color: #000;
  border-radius: 4px;
  object-fit: cover; /* 确保图片内容也是覆盖模式 */
}
.image-slot-error {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.image-slot-loading {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 30px;
}
</style>