// frontend/src/stores/media.js (修改后)
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
// --- 核心修改 1: 导入 API 配置 ---
import { API_BASE_URL } from '@/config/apiConfig';

export const useMediaStore = defineStore('media', () => {
  const searchResults = ref([])
  const isLoading = ref(false)
  const libraries = ref([])
  const activeBatchTaskId = ref(null)

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  function resetLoading() {
    isLoading.value = false
  }

  async function fetchLibraries() {
    isLoading.value = true
    try {
      // --- 核心修改 2: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/media/libraries`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '获取媒体库失败')
      libraries.value = data
    } catch (error) {
      showMessage('error', `获取媒体库失败: ${error.message}`)
      libraries.value = []
    } finally {
      isLoading.value = false
    }
  }

  async function searchMedia(query) {
    if (!query) {
      showMessage('warning', '请输入搜索内容！')
      return
    }
    isLoading.value = true
    searchResults.value = []
    try {
      // --- 核心修改 3: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/media/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '搜索失败')
      if (data.length === 0) {
        showMessage('info', '未找到相关媒体。')
      }
      searchResults.value = data
    } catch (error) {
      showMessage('error', `搜索失败: ${error.message}`)
    } finally {
      isLoading.value = false
    }
  }

  async function downloadSingleItem(itemId, contentTypes) {
    if (contentTypes.length === 0) {
      showMessage('warning', '请至少选择一种下载内容！')
      return
    }
    isLoading.value = true
    try {
      // --- 核心修改 4: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/media/download-item`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, content_types: contentTypes }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '下载失败')
      showMessage('success', `项目 ${itemId} 下载任务完成！`)
    } catch (error) {
      showMessage('error', `下载失败: ${error.message}`)
    } finally {
      isLoading.value = false
    }
  }

  async function startBatchDownload(request) {
    if (request.content_types.length === 0) {
      showMessage('warning', '请至少选择一种下载内容！')
      return
    }
    if (request.mode === 'byType' && !request.media_type) {
      showMessage('warning', '在“按媒体类型”模式下，必须选择电影或电视剧。')
      return
    }
    if (request.mode === 'byLibrary' && (!request.library_ids || request.library_ids.length === 0)) {
      showMessage('warning', '在“按媒体库”模式下，必须至少选择一个媒体库。')
      return
    }

    isLoading.value = true
    try {
      // --- 核心修改 5: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/media/batch-download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动失败')
      
      activeBatchTaskId.value = data.task_id
      showMessage('success', data.message)

    } catch (error) {
      showMessage('error', `启动批量下载失败: ${error.message}`)
    } finally {
      isLoading.value = false
    }
  }
  
  function clearActiveBatchTask() {
    activeBatchTaskId.value = null
  }

  return { 
    searchResults, 
    isLoading, 
    libraries, 
    activeBatchTaskId,
    resetLoading,
    fetchLibraries, 
    searchMedia, 
    downloadSingleItem, 
    startBatchDownload,
    clearActiveBatchTask
  }
})