// frontend/src/stores/fileScraper.js (代码块替换)

import { ref, computed, watch, nextTick } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig'
import { useTaskStore } from './task'

export const useFileScraperStore = defineStore('fileScraper', () => {
  const taskStore = useTaskStore()

  // --- State ---
  const config = ref({
    scan_directory: '',
    file_extensions: ['.mp4', '.mkv', '.strm'],
    overwrite_existing: false,
    batch_cooldown: 2.0,
    source_priority: ['xchina.co']
  })
  const isConfigLoaded = ref(false)
  const isScanning = ref(false)
  const isBatchScraping = ref(false)
  const scannedFiles = ref([])
  const activeScanTaskId = ref(null)
  const activeBatchScrapeTaskId = ref(null)
  // --- 新增 State ---
  const selectedFile = ref(null)
  const scrapedData = ref(null) // 用于存储单次刮削成功后的临时数据
  const nfoContent = ref('') // 用于存储NFO文件内容
  const isNfoLoading = ref(false)
  // --- 新增结束 ---

  // --- Getters ---
  const scanTask = computed(() => {
    if (!activeScanTaskId.value) return null
    return taskStore.tasks.find(t => t.id === activeScanTaskId.value)
  })

  const batchScrapeTask = computed(() => {
    if (!activeBatchScrapeTaskId.value) return null
    return taskStore.tasks.find(t => t.id === activeBatchScrapeTaskId.value)
  })

  // --- Actions ---
  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  async function fetchNfoContent(path) {
    if (!path) return
    isNfoLoading.value = true
    nfoContent.value = ''
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/media-file?path=${encodeURIComponent(path)}&file_type=nfo`)
      if (!response.ok) {
        if (response.status !== 404) { // 404是正常情况，说明文件不存在
          throw new Error(`服务器错误: ${response.statusText}`)
        }
        return
      }
      nfoContent.value = await response.text()
    } catch (error) {
      console.error('获取NFO内容失败:', error)
      nfoContent.value = `加载NFO文件失败: ${error.message}`
    } finally {
      isNfoLoading.value = false
    }
  }

  function selectFile(file) {
    selectedFile.value = file
    scrapedData.value = null // 切换选择时，清除上一个的临时刮削结果
    if (file && file.nfo_path) {
      fetchNfoContent(file.nfo_path)
    } else {
      nfoContent.value = ''
    }
  }
  // --- 新增结束 ---

  async function fetchConfig() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/config`)
      if (!response.ok) throw new Error('获取配置失败')
      const data = await response.json()
      config.value = data
      isConfigLoaded.value = true
    } catch (error) {
      showMessage('error', `获取配置失败: ${error.message}`)
    }
  }

  async function saveConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '保存失败')
      config.value = { ...newConfig }
      showMessage('success', data.message)
      return true
    } catch (error) {
      showMessage('error', `保存配置失败: ${error.message}`)
      return false
    }
  }

  async function saveUrls(item, newUrls) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/update-urls`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: item.path, urls: newUrls })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存URL失败');
      
      // 更新本地状态
      const index = scannedFiles.value.findIndex(f => f.path === item.path);
      if (index !== -1) {
        scannedFiles.value[index].urls = { ...newUrls };
      }
      showMessage('success', data.message);
      return true;
    } catch (error) {
      showMessage('error', `保存URL失败: ${error.message}`);
      return false;
    }
  }

  async function startScan() {
    if (isScanning.value) {
      showMessage('warning', '已有扫描任务正在进行中')
      return
    }
    isScanning.value = true
    scannedFiles.value = []
    selectFile(null) // --- 新增：扫描开始时清空选择 ---
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/scan`, { method: 'POST' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动扫描失败')
      activeScanTaskId.value = data.task_id
      showMessage('info', '扫描任务已启动，请在下方查看进度...')

      const unwatch = watch(() => taskStore.tasks, (newTasks, oldTasks) => {
        const currentTask = newTasks.find(t => t.id === activeScanTaskId.value);
        const oldTask = oldTasks ? oldTasks.find(t => t.id === activeScanTaskId.value) : null;

        if (currentTask && (!oldTask || currentTask.status !== oldTask.status) && ['completed', 'failed', 'cancelled'].includes(currentTask.status)) {
          if (currentTask.status === 'completed' && currentTask.result) {
            scannedFiles.value = currentTask.result
            showMessage('success', `扫描完成！共找到 ${currentTask.result.length} 个项目。`)
          } else if (currentTask.status === 'failed') {
            showMessage('error', '扫描任务失败！')
          } else {
            showMessage('warning', '扫描任务已取消。')
          }
          isScanning.value = false
          activeScanTaskId.value = null
          unwatch()
        } else if (oldTask && !currentTask) {
          isScanning.value = false;
          activeScanTaskId.value = null;
          unwatch();
        }
      }, { deep: true });
    } catch (error) {
      showMessage('error', `启动扫描失败: ${error.message}`)
      isScanning.value = false
    }
  }

  async function startBatchScrape() {
    if (isBatchScraping.value) {
      showMessage('warning', '已有批量刮削任务正在进行中')
      return
    }
    isBatchScraping.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/batch-scrape`, { method: 'POST' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动批量刮削失败')
      activeBatchScrapeTaskId.value = data.task_id
      showMessage('info', '批量刮削任务已启动...')

      const unwatch = watch(batchScrapeTask, (currentTask) => {
        if (!currentTask) return
        if (['completed', 'failed', 'cancelled'].includes(currentTask.status)) {
          showMessage(
            currentTask.status === 'completed' ? 'success' : 'warning',
            `批量刮削任务已${currentTask.status === 'completed' ? '完成' : '结束'}！`
          )
          isBatchScraping.value = false
          activeBatchScrapeTaskId.value = null
          startScan()
          unwatch()
        }
      })
    } catch (error) {
      showMessage('error', `启动批量刮削失败: ${error.message}`)
      isBatchScraping.value = false
    }
  }

  async function startSingleScrape(item) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/file-scraper/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: item.path, urls: item.urls })
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || '刮削失败')

      if (result.success) {
        const getBasename = (path) => path.substring(path.lastIndexOf('\\') + 1).substring(path.lastIndexOf('/') + 1);
        const itemName = getBasename(item.path);

        // --- 核心修改：增加对 "已跳过" 消息的处理分支 ---
        if (result.message === '已跳过') {
          showMessage('info', `'${itemName}' 已跳过，原因：元数据已存在且未开启覆盖。`);
        } else {
          // 只有在真正执行了刮削时，才更新UI状态
          showMessage('success', `'${itemName}' 刮削成功！`);
          
          scrapedData.value = result.data
          
          const index = scannedFiles.value.findIndex(f => f.path === item.path)
          if (index !== -1) {
            const updatedFile = { ...scannedFiles.value[index] }
            updatedFile.has_metadata = result.final_metadata_status
            if (result.new_path) {
              updatedFile.path = result.new_path
            }
            updatedFile.nfo_path = result.nfo_file_path
            updatedFile.poster_path = result.poster_file_path
            scannedFiles.value.splice(index, 1, updatedFile)
            
            selectFile(null);
            await nextTick();
            selectFile(updatedFile);
          }
        }
        // --- 修改结束 ---
      } else {
        showMessage('warning', `刮削操作未执行: ${result.message}`)
      }
      return result.success
    } catch (error) {
      showMessage('error', `刮削失败: ${error.message}`)
      return false
    }
  }

  return {
    config,
    isConfigLoaded,
    isScanning,
    isBatchScraping,
    scannedFiles,
    activeScanTaskId,
    activeBatchScrapeTaskId,
    scanTask,
    batchScrapeTask,
    selectedFile,
    scrapedData,
    nfoContent,
    isNfoLoading,
    fetchConfig,
    saveConfig,
    startScan,
    startBatchScrape,
    selectFile,
    startSingleScrape,
    saveUrls
  }
})