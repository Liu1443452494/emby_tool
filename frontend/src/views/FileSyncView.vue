<template>
  <div class="file-sync-page">
    <div class="page-header">
      <h2>网盘文件重命名</h2>
      <p>将本地已重命名的文件同步到网盘，或扫描网盘与 Emby 对比生成重命名计划。</p>
    </div>

    <!-- --- 核心修改：使用 ElCollapse 包裹路径配置 --- -->
    <el-collapse class="config-collapse" style="margin-bottom: 20px;">
      <el-collapse-item name="1">
        <template #title>
          <div class="collapse-title">
            <el-icon><Setting /></el-icon>
            <span>网盘路径配置</span>
            <el-tag size="small" type="info" style="margin-left: 10px;">点击展开/折叠</el-tag>
          </div>
        </template>
        <div class="config-card-content">
          <el-alert
            title="重要：路径配置指南"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 20px;"
          >
            <p>此功能需要您将网盘挂载到本工具容器可以访问的路径。程序将根据您提供的规则，将 Emby 中的路径转换为网盘路径。</p>
          </el-alert>
          <el-form label-position="top" class="path-config-form">
            <el-form-item label="Emby 媒体库路径前缀 (From)">
              <el-input v-model="pathFrom" placeholder="例如: /media" />
            </el-form-item>
            <el-form-item label="网盘在容器内的挂载点路径 (To)">
              <el-input v-model="pathTo" placeholder="例如: /clouddrive" />
            </el-form-item>
          </el-form>
        </div>
      </el-collapse-item>
    </el-collapse>
    <!-- --- 结束修改 --- -->

    <el-card class="box-card results-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>待办任务列表</span>
          <div class="header-actions">
            <el-button @click="openScanDialog">按剧集扫描网盘...</el-button>
            <el-button type="primary">刷新日志列表</el-button>
          </div>
        </div>
      </template>
      <div class="table-container">
        <el-table :data="renamerStore.renamePlan" height="100%" stripe empty-text="暂无待办任务，请先扫描或刷新日志">
          <el-table-column type="selection" width="45" />
          <el-table-column prop="series_name" label="剧集" width="200" />
          <el-table-column prop="episode_number" label="分集" width="80" />
          <el-table-column prop="old_filename" label="旧文件名" show-overflow-tooltip />
          <el-table-column prop="new_filename" label="新文件名" show-overflow-tooltip />
        </el-table>
      </div>
      <div class="table-footer">
        <el-button type="danger" plain>忽略选中项</el-button>
        <el-button type="success">同步选中项到网盘</el-button>
      </div>
    </el-card>

    <!-- 按剧集扫描对话框 -->
    <el-dialog
      v-model="isScanDialogVisible"
      title="按剧集扫描网盘"
      width="60%"
      top="5vh"
      :close-on-click-modal="false"
    >
      <div class="scan-dialog-content">
        <el-form @submit.prevent="handleSearch" class="search-form">
          <el-input v-model="searchQuery" placeholder="输入剧集标题..." clearable />
          <el-button type="primary" native-type="submit" :loading="mediaStore.isLoading">搜索 Emby</el-button>
        </el-form>
        <div class="search-results-table" v-loading="mediaStore.isLoading">
          <el-table
            :data="mediaStore.searchResults"
            height="100%"
            highlight-current-row
            @current-change="handleSeriesSelection"
            empty-text="请输入关键词搜索"
          >
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="70" />
          </el-table>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isScanDialogVisible = false">取消</el-button>
          <el-button 
            type="primary" 
            @click="handleStartScan"
            :disabled="!selectedSeriesId"
            :loading="renamerStore.isLoading"
          >
            开始扫描
          </el-button>
        </span>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useStorage } from '@vueuse/core'
import { useMediaStore } from '@/stores/media'
import { useRenamerStore } from '@/stores/renamer'
import { useTaskStore } from '@/stores/task'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'

const mediaStore = useMediaStore()
const renamerStore = useRenamerStore()
const taskStore = useTaskStore()

const pathFrom = useStorage('renamer-path-from', '/media')
const pathTo = useStorage('renamer-path-to', '/clouddrive')

const isScanDialogVisible = ref(false)
const searchQuery = ref('')
const selectedSeriesId = ref(null)

onMounted(() => {
  taskStore.connect()
})

watch(() => renamerStore.activeScanTaskId, (newTaskId, oldTaskId) => {
  if (oldTaskId && !newTaskId) {
    const finishedTask = taskStore.tasks.find(t => t.id === oldTaskId)
    if (finishedTask && finishedTask.status === 'completed') {
      renamerStore.setRenamePlan(finishedTask.result || [])
      ElMessage.success('网盘扫描完成！')
    } else if (finishedTask && finishedTask.status === 'failed') {
      ElMessage.error('网盘扫描失败，请检查日志。')
    }
  }
})

const openScanDialog = () => {
  isScanDialogVisible.value = true
  searchQuery.value = ''
  mediaStore.searchResults = []
  selectedSeriesId.value = null
}

const handleSearch = () => {
  mediaStore.searchMedia(searchQuery.value)
}

const handleSeriesSelection = (row) => {
  selectedSeriesId.value = row ? row.Id : null
}

const handleStartScan = async () => {
  if (!pathFrom.value || !pathTo.value) {
    ElMessage.warning('请先展开配置，并填写完整的路径转换规则！')
    return
  }
  const payload = {
    series_id: selectedSeriesId.value,
    path_from: pathFrom.value,
    path_to: pathTo.value
  }
  const result = await renamerStore.startScan(payload)
  if (result.success) {
    isScanDialogVisible.value = false
  }
}
</script>

<style scoped>
.file-sync-page {
  padding: 0 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
  margin-bottom: 20px;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.config-collapse {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  --el-collapse-border-color: transparent;
}
.config-collapse :deep(.el-collapse-item__header) {
  background-color: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 0 15px;
  height: 50px;
}
.config-collapse :deep(.el-collapse-item__header.is-active) {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.config-collapse :deep(.el-collapse-item__wrap) {
  background-color: var(--el-bg-color-overlay);
  border-bottom-left-radius: 8px;
  border-bottom-right-radius: 8px;
}
.config-collapse :deep(.el-collapse-item__content) {
  padding: 0;
}
.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: bold;
  font-size: 1rem;
}
.config-card-content {
  padding: 20px;
}

.box-card {
  border: 1px solid var(--el-border-color-lighter);
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}
.path-config-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.results-card {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.results-card :deep(.el-card__body) {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 20px;
}
.table-container {
  flex-grow: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}
.table-footer {
  padding-top: 20px;
  text-align: right;
}
.scan-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
  height: 65vh;
}
.search-form {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.search-results-table {
  flex-grow: 1;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}
</style>