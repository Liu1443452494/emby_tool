// frontend/src/views/DoubanFixerView.vue (修改后)
<template>
  <div class="douban-fixer-page">
    <div class="page-header">
      <h2>豆瓣ID修复器</h2>
      <p>自动扫描 Emby 媒体库中缺少豆瓣ID的影视，并尝试从豆瓣搜索匹配。匹配失败的项目将进入下方列表供手动处理。</p>
    </div>

    <div class="main-layout">
      <!-- 左侧控制面板 -->
      <div class="controls-panel">
        <div class="control-section">
          <h3>1. 选择扫描范围</h3>
          <el-radio-group v-model="scanScope" class="scope-radio-group">
            <el-radio value="all">所有媒体库</el-radio>
            <el-radio value="media_type">按媒体类型</el-radio>
            <el-radio value="library">按媒体库</el-radio>
          </el-radio-group>
          <div class="sub-options">
            <div v-if="scanScope === 'media_type'">
              <el-radio-group v-model="selectedMediaType">
                <el-radio value="Movie">仅电影</el-radio>
                <el-radio value="Series">仅电视剧</el-radio>
              </el-radio-group>
            </div>
            <div v-if="scanScope === 'library'">
              <el-select 
                v-model="selectedLibraryIds" 
                multiple 
                placeholder="请选择媒体库" 
                style="width: 100%;" 
                filterable
                :loading="mediaStore.isLoading"
              >
                <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </div>
          </div>
        </div>

        <div class="control-section">
          <h3>2. 执行操作</h3>
          <div class="action-bar">
            <el-button 
              type="primary" 
              @click="handleFullScan" 
              :loading="store.isScanning"
              :disabled="isTaskRunning"
              class="action-button"
            >
              扫描并自动匹配
            </el-button>
            <el-button 
              @click="store.fetchCachedItems()" 
              :loading="store.isLoading"
              :disabled="isTaskRunning"
              class="action-button"
            >
              刷新失败缓存
            </el-button>
            <el-button 
              type="danger" 
              @click="store.clearCache()"
              :disabled="isTaskRunning || store.cachedItems.length === 0"
              class="action-button"
            >
              清空失败缓存
            </el-button>
          </div>
        </div>
        
        <div class="control-section task-status-section">
          <h3>3. 任务状态</h3>
          <div class="action-bar-info">
            <el-alert
              v-if="isTaskRunning"
              :title="`扫描任务 (${runningTask.name}) 正在后台运行中...`"
              type="info"
              show-icon
              :closable="false"
            >
              <p v-if="runningTask.total > 0">进度: {{ runningTask.progress }} / {{ runningTask.total }}</p>
              <p v-else>已发现 {{ runningTask.progress }} 个媒体项</p>
            </el-alert>
            <span v-else>
              当前无扫描任务运行。
            </span>
          </div>
        </div>
      </div>

      <!-- 右侧结果展示区 -->
      <div class="results-panel">
        <div class="table-header">
          <h3>匹配失败缓存 ({{ store.cachedItems.length }} 项)</h3>
        </div>
        <div class="table-container">
          <el-table 
            :data="store.cachedItems" 
            v-loading="store.isLoading"
            style="width: 100%" 
            height="100%"
            empty-text="太棒了！没有匹配失败的项目。"
          >
            <el-table-column prop="Name" label="Emby 标题" min-width="250" />
            <el-table-column prop="ProductionYear" label="年份" width="100" />
            <el-table-column prop="Type" label="类型" width="120" />
            <el-table-column prop="Id" label="Emby ItemID" width="200" />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="scope">
                <el-button
                  type="success"
                  size="small"
                  @click="handleManualSearch(scope.row)"
                  :disabled="isTaskRunning"
                >
                  手动搜索
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>

    <!-- 手动搜索对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="`为 “${activeItem?.Name}” 手动匹配豆瓣ID`"
      width="70%"
      top="5vh"
      :close-on-click-modal="false"
    >
      <div class="dialog-content">
        <el-form @submit.prevent="searchInDialog" class="dialog-search-form">
          <el-input v-model="dialogSearchQuery" placeholder="输入搜索关键词..." clearable />
          <el-button type="primary" native-type="submit" :loading="store.isSearching">搜索</el-button>
        </el-form>

        <div class="results-container" v-loading="store.isSearching">
          <div v-if="store.searchResults.length > 0" class="results-grid">
            <el-card v-for="result in store.searchResults" :key="result.id" class="result-card">
              <div class="card-content">
                <!-- 关键修改：使用后端代理来加载图片 -->
                <el-image :src="getProxiedImageUrl(result.poster)" fit="cover" class="result-poster">
                  <template #error><div class="image-slot">无图</div></template>
                </el-image>
                <div class="result-info">
                  <h4 class="result-title">{{ result.title }} ({{ result.year }})</h4>
                  <p class="result-details">{{ result.info }}</p>
                  <el-button 
                    type="success" 
                    @click="handleConfirmMatch(result)" 
                    :loading="store.isUpdating"
                    class="confirm-button"
                  >
                    就是这个
                  </el-button>
                </div>
              </div>
            </el-card>
          </div>
          <el-empty v-else description="暂无搜索结果，请尝试不同关键词" />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useDoubanFixerStore } from '@/stores/doubanFixer'
import { useTaskStore } from '@/stores/task'
import { useMediaStore } from '@/stores/media'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStorage } from '@vueuse/core'
import { API_BASE_URL } from '@/config/apiConfig' // 导入 API_BASE_URL

const store = useDoubanFixerStore()
const taskStore = useTaskStore()
const mediaStore = useMediaStore()

const dialogVisible = ref(false)
const activeItem = ref(null)
const dialogSearchQuery = ref('')

const scanScope = useStorage('doubanfixer-scan-scope', 'all')
const selectedMediaType = useStorage('doubanfixer-media-type', 'Movie')
const selectedLibraryIds = useStorage('doubanfixer-library-ids', [])

const runningTask = computed(() => 
  taskStore.tasks.find(task => task.name.startsWith('豆瓣ID修复') && task.status === 'running')
)
const isTaskRunning = computed(() => !!runningTask.value)

onMounted(() => {
  store.fetchCachedItems()
  taskStore.connect()
  mediaStore.fetchLibraries()
})

watch(isTaskRunning, (newValue, oldValue) => {
  if (oldValue && !newValue) {
    ElMessage.success('扫描任务已结束，正在刷新缓存列表...');
    setTimeout(() => {
      store.fetchCachedItems();
    }, 1000);
  }
});

const handleFullScan = () => {
  if (isTaskRunning.value) {
    ElMessage.warning('已有扫描任务在运行，请勿重复启动。')
    return
  }

  if (scanScope.value === 'library' && selectedLibraryIds.value.length === 0) {
    ElMessage.warning('请至少选择一个媒体库。')
    return
  }

  const payload = {
    scope: scanScope.value,
    media_type: scanScope.value === 'media_type' ? selectedMediaType.value : null,
    library_ids: scanScope.value === 'library' ? selectedLibraryIds.value : null,
  }
  store.startFullScan(payload)
}

const handleManualSearch = (row) => {
  activeItem.value = row
  dialogSearchQuery.value = row.Name
  store.searchResults = []
  dialogVisible.value = true
}

const searchInDialog = () => {
  if (!dialogSearchQuery.value) {
    ElMessage.warning('请输入搜索关键词。')
    return
  }
  store.manualSearch(dialogSearchQuery.value)
}

const handleConfirmMatch = async (doubanResult) => {
  try {
    await ElMessageBox.confirm(
      `确定要将 Emby 媒体 “${activeItem.value.Name}” 的豆瓣ID更新为 “${doubanResult.title}” (ID: ${doubanResult.id}) 吗？`,
      '最终确认',
      {
        confirmButtonText: '确定更新',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    const success = await store.manualUpdate(activeItem.value.Id, doubanResult.id)
    if (success) {
      dialogVisible.value = false
    }
  } catch (error) {
    // 用户点击取消，无需处理
  }
}

// 新增：获取代理图片URL的辅助函数
const getProxiedImageUrl = (originalUrl) => {
  if (!originalUrl) return ''
  return `${API_BASE_URL}/api/image-proxy?url=${encodeURIComponent(originalUrl)}`
}
</script>

<style scoped>
.douban-fixer-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 0 20px;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.main-layout {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 20px;
  flex-grow: 1;
  overflow: hidden;
  padding-top: 20px;
}

.controls-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}

.control-section {
  background-color: var(--el-bg-color-overlay);
  padding: 20px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}
.control-section h3 {
  margin: 0 0 15px 0;
  font-size: 1.1rem;
}

.scope-radio-group {
  margin-bottom: 15px;
}
.sub-options {
  padding-left: 10px;
  margin-top: 10px;
}

.action-bar {
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.action-button {
  width: 100%;
  margin: 0 !important;
}

.task-status-section .action-bar-info {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.results-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.table-header {
  flex-shrink: 0;
  margin-bottom: 15px;
}
.table-header h3 {
  margin: 0;
  font-size: 1.2rem;
}
.table-container {
  flex-grow: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}

.dialog-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: 75vh;
}
.dialog-search-form {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.results-container {
  flex-grow: 1;
  overflow-y: auto;
  background-color: var(--el-fill-color-lighter);
  border-radius: 4px;
  padding: 15px;
}
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(450px, 1fr));
  gap: 15px;
}
.result-card {
  border: 1px solid var(--el-border-color);
}
.card-content {
  display: flex;
  gap: 15px;
}
.result-poster {
  width: 100px;
  height: 150px;
  flex-shrink: 0;
  border-radius: 4px;
  background-color: var(--el-fill-color);
}
.image-slot {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.result-info {
  display: flex;
  flex-direction: column;
  flex-grow: 1;
}
.result-title {
  margin: 0 0 8px 0;
  font-size: 1rem;
  font-weight: bold;
}
.result-details {
  margin: 0 0 10px 0;
  font-size: 0.85rem;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  flex-grow: 1;
}
.confirm-button {
  align-self: flex-end;
}
</style>