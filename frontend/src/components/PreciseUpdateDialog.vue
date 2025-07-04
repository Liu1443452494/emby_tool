<!-- 文件路径: frontend/src/components/PreciseUpdateDialog.vue (新文件) -->
<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="$emit('update:visible', $event)"
    title="精准覆盖 GitHub 截图"
    width="80%"
    top="5vh"
    destroy-on-close
    @open="handleOpen"
  >
    <div class="precise-update-dialog-content">
      <div class="dialog-toolbar">
        <el-alert
          title="操作说明"
          type="info"
          show-icon
          :closable="false"
        >
          <p>本工具已自动扫描您本地的 `EpisodeScreenshots` 文件夹，并匹配了 Emby 中的信息。请勾选您希望上传以覆盖 GitHub 远程截图的分集。</p>
        </el-alert>
        <el-input
          v-model="filterText"
          placeholder="按剧集或分集标题筛选..."
          clearable
          :prefix-icon="Search"
        />
      </div>
      <div class="table-container" v-loading="isLoading">
        <el-table
          :data="filteredData"
          height="100%"
          border
          @selection-change="handleSelectionChange"
          empty-text="没有在本地找到任何截图文件，或 Emby 匹配失败。"
        >
          <el-table-column type="selection" width="55" />
          <el-table-column prop="series_name" label="剧集" width="250" show-overflow-tooltip sortable />
          <el-table-column label="分集" width="100" sortable :sort-by="sortByEpisode">
            <template #default="scope">
              S{{ String(scope.row.season_number).padStart(2, '0') }}E{{ String(scope.row.episode_number).padStart(2, '0') }}
            </template>
          </el-table-column>
          <el-table-column prop="episode_name" label="分集标题 (来自Emby)" show-overflow-tooltip />
        </el-table>
      </div>
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">关闭</el-button>
      <el-button 
        type="danger" 
        @click="handlePreciseUpdate" 
        :disabled="selectedEpisodes.length === 0"
        :loading="isUpdating"
      >
        开始更新选中的 ({{ selectedEpisodes.length }}) 项
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Search } from '@element-plus/icons-vue';
import { API_BASE_URL } from '@/config/apiConfig';
import _ from 'lodash';

const props = defineProps({
  visible: Boolean,
  config: Object, // 从父组件接收最新的 refresher config
});
const emit = defineEmits(['update:visible']);

const isLoading = ref(false);
const isUpdating = ref(false);
const allData = ref([]);
const selectedEpisodes = ref([]);
const filterText = ref('');

const filteredData = computed(() => {
  if (!filterText.value) {
    return allData.value;
  }
  return allData.value.filter(item => 
    item.series_name.toLowerCase().includes(filterText.value.toLowerCase()) ||
    item.episode_name.toLowerCase().includes(filterText.value.toLowerCase())
  );
});

const handleOpen = async () => {
  isLoading.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/local-screenshots-for-update`);
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || '获取列表失败');
    }
    const data = await response.json();
    allData.value = _.sortBy(data, ['series_name', 'season_number', 'episode_number']);
  } catch (error) {
    ElMessage.error(`获取可更新列表失败: ${error.message}`);
    allData.value = [];
  } finally {
    isLoading.value = false;
  }
};

const handleSelectionChange = (selection) => {
  selectedEpisodes.value = selection;
};

const sortByEpisode = (rowA, rowB) => {
  const sA = rowA.season_number;
  const eA = rowA.episode_number;
  const sB = rowB.season_number;
  const eB = rowB.episode_number;
  if (sA !== sB) {
    return sA - sB;
  }
  return eA - eB;
};

const handlePreciseUpdate = async () => {
  if (selectedEpisodes.value.length === 0) {
    ElMessage.warning('请至少选择一个分集进行更新。');
    return;
  }

  try {
    await ElMessageBox.confirm(
      `即将为您选中的 ${selectedEpisodes.value.length} 个分集，从本地查找新截图并上传覆盖到 GitHub。请确保您已在本地准备好了新的截图文件。是否继续？`,
      '确认精准覆盖操作',
      { confirmButtonText: '开始更新', cancelButtonText: '取消', type: 'info' }
    );

    isUpdating.value = true;
    
    // 按剧集对所选项进行分组
    const groupedBySeries = _.groupBy(selectedEpisodes.value, 'series_tmdb_id');
    
    for (const series_tmdb_id in groupedBySeries) {
        const episodesInSeries = groupedBySeries[series_tmdb_id];
        const payload = {
            series_tmdb_id: series_tmdb_id,
            series_name: episodesInSeries[0].series_name,
            episodes: episodesInSeries.map(ep => ({
                season_number: ep.season_number,
                episode_number: ep.episode_number
            })),
            config: props.config
        };

        const response = await fetch(`${API_BASE_URL}/api/episode-refresher/precise-upload-from-local`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `剧集 ${payload.series_name} 的更新任务启动失败`);
        
        ElMessage.success(`剧集《${payload.series_name}》的更新任务已启动。`);
    }
    
    emit('update:visible', false);

  } catch (error) {
    if (error && error.message) {
      ElMessage.error(`启动任务失败: ${error.message}`);
    }
  } finally {
    isUpdating.value = false;
  }
};
</script>

<style scoped>
.precise-update-dialog-content {
  height: 70vh;
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.dialog-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}
.dialog-toolbar .el-alert {
  flex-grow: 1;
}
.dialog-toolbar .el-input {
  width: 300px;
  flex-shrink: 0;
}
.table-container {
  flex-grow: 1;
  overflow: hidden;
}
</style>