// frontend/src/stores/media.js (修改后)

import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig';
import { useConfigStore } from './config';

export const useMediaStore = defineStore('media', () => {
  const configStore = useConfigStore();
  const appConfig = computed(() => configStore.appConfig);
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

  async function startBatchDownload(payload) {
    if (payload.content_types.length === 0) {
      showMessage('warning', '请至少选择一种下载内容！')
      return
    }
    
    const scope = payload.scope;
    if (scope.mode === 'by_library' && (!scope.library_ids || scope.library_ids.length === 0)) {
      showMessage('warning', '在“按媒体库”模式下，必须至少选择一个媒体库。')
      return
    }

    isLoading.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/media/batch-download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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
    appConfig,
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