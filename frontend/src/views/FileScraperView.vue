<!-- frontend/src/views/FileScraperView.vue (完整文件覆盖) -->
<template>
  <div class="file-scraper-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <h2>手动文件刮削器</h2>
        <p>手动为 Emby 媒体库中难以自动识别的媒体文件刮削元数据和图片。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Setting" @click="isSettingsDialogVisible = true">设置</el-button>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button 
          type="primary" 
          :icon="Search" 
          @click="scraperStore.startScan" 
          :loading="scraperStore.isScanning"
        >
          {{ scraperStore.isScanning ? '正在扫描...' : '扫描目录' }}
        </el-button>
        <el-button 
          type="success" 
          :icon="Download" 
          @click="scraperStore.startBatchScrape"
          :loading="scraperStore.isBatchScraping"
          :disabled="scraperStore.isScanning || filteredFiles.length === 0"
        >
          批量刮削
        </el-button>
        <el-select v-model="filterStatus" placeholder="筛选状态" style="width: 180px;" clearable>
          <el-option label="全部" value="all" />
          <el-option label="仅缺元数据" value="missing" />
          <el-option label="仅有元数据" value="existing" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <span v-if="scraperStore.scanTask" class="task-status">
          扫描进度: {{ scraperStore.scanTask.progress }} / {{ scraperStore.scanTask.total }}
        </span>
        <span v-if="scraperStore.batchScrapeTask" class="task-status">
          刮削进度: {{ scraperStore.batchScrapeTask.progress }} / {{ scraperStore.batchScrapeTask.total }}
        </span>
      </div>
    </div>

    <!-- 主内容区 -->
    <el-container class="main-content">
      <!-- 左侧列表 -->
      <el-aside width="60%" class="list-panel">
        <el-table
          :data="filteredFiles"
          v-loading="scraperStore.isScanning"
          element-loading-text="正在扫描文件，请稍候..."
          height="100%"
          style="width: 100%"
          border
          highlight-current-row
          @row-click="scraperStore.selectFile"
          empty-text="请先配置扫描目录并开始扫描"
        >
          <el-table-column type="index" width="50" />
          <el-table-column prop="path" label="文件/文件夹路径" min-width="400">
            <template #default="{ row }">
              <div class="path-cell">
                <el-icon :size="16" style="margin-right: 8px;">
                  <Folder v-if="row.type === 'dir'" />
                  <Document v-else />
                </el-icon>
                <span>{{ row.path }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="元数据状态" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="row.has_metadata ? 'success' : 'warning'">
                {{ row.has_metadata ? '完整' : '缺失' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" align="center" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" size="small" @click.stop="handleSingleScrape(row)">刮削</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-aside>
      <!-- 右侧详情 -->
      <el-main class="detail-panel">
        <div v-if="scraperStore.selectedFile" class="detail-content">
          <div class="poster-section">
            <el-image :src="posterUrl" fit="contain" class="poster-image">
              <template #error>
                <div class="image-slot">暂无海报</div>
              </template>
            </el-image>
          </div>
          <div class="info-section">
            <h3>{{ scraperStore.scrapedData?.title || scraperStore.selectedFile.path }}</h3>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="路径">{{ scraperStore.selectedFile.path }}</el-descriptions-item>
              <el-descriptions-item label="元数据">{{ scraperStore.selectedFile.has_metadata ? '完整' : '缺失' }}</el-descriptions-item>
            </el-descriptions>
            
            <h4>刮削网址 <el-button link type="primary" @click="openUrlDialog(scraperStore.selectedFile)">编辑</el-button></h4>
            <div v-if="Object.keys(scraperStore.selectedFile.urls).length > 0" class="url-list">
               <el-tag v-for="(url, domain) in scraperStore.selectedFile.urls" :key="domain" class="url-tag">
                {{ domain }}: {{ url }}
              </el-tag>
            </div>
            <p v-else class="text-secondary">未设置刮削网址</p>

            <h4>简介</h4>
            <p class="plot">{{ scraperStore.scrapedData?.plot || '暂无简介' }}</p>

            <h4>NFO 内容</h4>
            <div class="nfo-content" v-loading="scraperStore.isNfoLoading">
              <pre>{{ scraperStore.nfoContent || '无NFO内容或文件不存在' }}</pre>
            </div>
          </div>
        </div>
        <el-empty v-else description="请从左侧列表选择一个项目" />
      </el-main>
    </el-container>

    <!-- 设置对话框 -->
    <el-dialog v-model="isSettingsDialogVisible" title="文件刮削器设置" width="700px">
      <el-form :model="localConfig" label-position="top">
        <el-form-item label="扫描目录">
          <el-input v-model="localConfig.scan_directory" placeholder="例如: /media/movies 或 D:\Movies" />
        </el-form-item>
        <el-form-item label="文件后缀 (多个请用英文逗号 , 分隔)">
          <el-input v-model="fileExtensionsProxy" placeholder=".mp4,.mkv,.strm" />
        </el-form-item>
        <el-form-item label="批量刮削冷却时间 (秒)">
          <el-input-number v-model="localConfig.batch_cooldown" :min="0" :step="0.5" />
        </el-form-item>
        
        <el-form-item label="覆盖现有元数据">
          <el-switch v-model="localConfig.overwrite_existing" />
          <div class="form-item-description">
            开启后，批量刮削会强制处理所有项目，并覆盖已有的 NFO 和图片文件。
          </div>
        </el-form-item>
        <el-form-item label="刮削源优先级">
          <!-- --- 核心修改：使用传统列表和按钮进行排序 --- -->
          <div class="priority-list-container">
            <div
              v-for="(tag, index) in localConfig.source_priority"
              :key="tag"
              class="priority-item"
            >
              <el-tag
                closable
                :disable-transitions="false"
                @close="handlePriorityTagClose(tag)"
                size="large"
              >
                {{ tag }}
              </el-tag>
              <div class="priority-controls">
                <el-button
                  :icon="ArrowUp"
                  circle
                  size="small"
                  :disabled="index === 0"
                  @click="movePriorityUp(index)"
                  title="上移"
                />
                <el-button
                  :icon="ArrowDown"
                  circle
                  size="small"
                  :disabled="index === localConfig.source_priority.length - 1"
                  @click="movePriorityDown(index)"
                  title="下移"
                />
              </div>
            </div>
            <div v-if="localConfig.source_priority.length === 0" class="el-form-item__description">
              暂无刮削源，请添加。
            </div>
          </div>
          <el-button class="button-new-tag" size="small" @click="showPriorityInput" style="margin-top: 8px;">
            + 添加源
          </el-button>
          <el-input
            v-if="priorityInputVisible"
            ref="priorityInputRef"
            v-model="priorityInputValue"
            class="ml-1 w-20"
            size="small"
            @keyup.enter="handlePriorityInputConfirm"
            @blur="handlePriorityInputConfirm"
            style="margin-top: 8px;"
          />
          <!-- --- 修改结束 --- -->
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="isSettingsDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑网址对话框 -->
    <el-dialog v-model="isUrlDialogVisible" :title="`编辑 '${currentItem?.path}' 的网址`" width="600px">
      <el-form :model="currentUrls" label-position="top">
        <el-form-item v-for="domain in scraperStore.config.source_priority" :key="domain" :label="domain">
          <el-input v-model="currentUrls[domain]" :placeholder="`请输入 ${domain} 的完整网址`" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="isUrlDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveUrls">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch, nextTick } from 'vue'

import { useFileScraperStore } from '@/stores/fileScraper'
import { Setting, Search, Download, Folder, Document, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig'
import _ from 'lodash'

const scraperStore = useFileScraperStore()

const isSettingsDialogVisible = ref(false)
const isUrlDialogVisible = ref(false)
const localConfig = ref({})
const currentItem = ref(null)
const currentUrls = ref({})
const filterStatus = ref('all')
const priorityInputVisible = ref(false)
const priorityInputValue = ref('')
const priorityInputRef = ref(null)


const movePriorityUp = (index) => {
  if (index === 0) return;
  const items = localConfig.value.source_priority;
  // 交换数组元素
  [items[index], items[index - 1]] = [items[index - 1], items[index]];
};

const movePriorityDown = (index) => {
  const items = localConfig.value.source_priority;
  if (index === items.length - 1) return;
  // 交换数组元素
  [items[index], items[index + 1]] = [items[index + 1], items[index]];
};
onMounted(() => {
  scraperStore.fetchConfig()
})

watch(() => scraperStore.config, (newConfig) => {
  localConfig.value = _.cloneDeep(newConfig)
}, { deep: true })

const fileExtensionsProxy = computed({
  get: () => localConfig.value.file_extensions?.join(',') || '',
  set: (val) => {
    localConfig.value.file_extensions = val.split(',').map(ext => ext.trim()).filter(Boolean)
  }
})

const filteredFiles = computed(() => {
  if (filterStatus.value === 'all' || !filterStatus.value) {
    return scraperStore.scannedFiles
  }
  const wantExisting = filterStatus.value === 'existing'
  return scraperStore.scannedFiles.filter(file => file.has_metadata === wantExisting)
})

const posterUrl = computed(() => {
  if (scraperStore.scrapedData?.poster_url) {
    return `${API_BASE_URL}/api/image-proxy?url=${encodeURIComponent(scraperStore.scrapedData.poster_url)}`
  }
  if (scraperStore.selectedFile?.poster_path) {
    return `${API_BASE_URL}/api/file-scraper/media-file?path=${encodeURIComponent(scraperStore.selectedFile.poster_path)}&file_type=poster&t=${new Date().getTime()}`
  }
  return ''
})

const handleSaveConfig = async () => {
  const success = await scraperStore.saveConfig(localConfig.value)
  if (success) {
    isSettingsDialogVisible.value = false
  }
}

const openUrlDialog = (item) => {
  currentItem.value = item
  currentUrls.value = _.cloneDeep(item.urls)
  isUrlDialogVisible.value = true
}

const handleSaveUrls = async () => {
  if (currentItem.value) {
    const success = await scraperStore.saveUrls(currentItem.value, currentUrls.value);
    if (success) {
      isUrlDialogVisible.value = false;
    }
  }
}

const handleSingleScrape = async (item) => {
  ElMessage.info(`正在为 '${item.path}' 开始刮削...`)
  await scraperStore.startSingleScrape(item)
}

const handlePriorityTagClose = (tag) => {
  localConfig.value.source_priority.splice(localConfig.value.source_priority.indexOf(tag), 1)
}

const showPriorityInput = () => {
  priorityInputVisible.value = true
  nextTick(() => {
    priorityInputRef.value.input.focus()
  })
}

const handlePriorityInputConfirm = () => {
  if (priorityInputValue.value) {
    localConfig.value.source_priority.push(priorityInputValue.value)
  }
  priorityInputVisible.value = false
  priorityInputValue.value = ''
}
</script>

<style scoped>
.file-scraper-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 0 20px;
}
.page-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 0; border-bottom: 1px solid var(--el-border-color-light); flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }
.toolbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 15px 0; flex-shrink: 0;
}
.toolbar-left, .toolbar-right { display: flex; align-items: center; gap: 15px; }
.task-status { font-size: 14px; color: var(--el-text-color-secondary); }
.main-content { flex-grow: 1; overflow: hidden; border-top: 1px solid var(--el-border-color-light); }
.list-panel { padding-right: 10px; border-right: 1px solid var(--el-border-color-light); }
.detail-panel { padding: 10px 20px; }
.path-cell { display: flex; align-items: center; }
.detail-content { display: flex; gap: 20px; }
.poster-section { flex-shrink: 0; width: 250px; }
.poster-image { width: 100%; height: 375px; background-color: var(--el-fill-color-light); border-radius: 8px; }
.image-slot { display: flex; justify-content: center; align-items: center; height: 100%; color: var(--el-text-color-secondary); }
.info-section { flex-grow: 1; }
.info-section h3 { margin-top: 0; }
.info-section h4 { margin: 20px 0 10px; }
.url-list { display: flex; flex-direction: column; gap: 5px; }
.url-tag { justify-content: flex-start; height: auto; padding: 4px 8px; line-height: 1.4; white-space: normal; }
.plot { font-size: 14px; color: var(--el-text-color-regular); line-height: 1.6; }
.nfo-content {
  background-color: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 10px;
  max-height: 200px;
  overflow-y: auto;
  font-size: 12px;
}
.nfo-content pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; }
.text-secondary { color: var(--el-text-color-secondary); font-style: italic; }
.form-item-description { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-top: 4px; }
.el-tag { margin-right: 5px; }
.button-new-tag { margin-left: 5px; }
.w-20 { width: 80px; }
.priority-list-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.priority-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  border-radius: 4px;
  background-color: var(--el-fill-color-light);
}
.priority-item .el-tag {
  border: none;
  background-color: transparent;
  padding-left: 0;
}
.priority-controls {
  display: flex;
  gap: 6px;
}
</style>