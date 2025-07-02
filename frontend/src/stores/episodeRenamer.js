// frontend/src/stores/episodeRenamer.js (新文件)

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig'

export const useEpisodeRenamerStore = defineStore('episodeRenamer', () => {
  const isLoading = ref(false)
  const logs = ref([])
  const isApplying = ref(false)
  const isSearching = ref(false)
  const searchResults = ref([])
  const isScanning = ref(false)

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  async function fetchLogs() {
    isLoading.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/episode-renamer/logs`)
      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || '获取日志失败')
      }
      // 获取的是所有日志，前端将根据 status 自行分类
      logs.value = await response.json()
    } catch (error) {
      showMessage('error', error.message)
      logs.value = []
    } finally {
      isLoading.value = false
    }
  }

  async function clearCompletedLogs() {
    try {
      await ElMessageBox.confirm(
        '确定要从日志文件中移除所有已完成的记录吗？',
        '确认操作',
        {
          confirmButtonText: '确定清理',
          cancelButtonText: '取消',
          type: 'info',
        }
      )
      const response = await fetch(`${API_BASE_URL}/api/episode-renamer/logs/clear-completed`, {
        method: 'POST',
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '清理失败')
      showMessage('success', data.message)
      await fetchLogs()
    } catch (error) {
      if (error !== 'cancel') {
        showMessage('error', error.message)
      }
    }
  }

  async function clearAllLogs() {
    try {
      await ElMessageBox.confirm(
        '危险操作！这将清空所有待处理和已完成的记录，且不可恢复。确定吗？',
        '警告',
        {
          confirmButtonText: '确定全部清空',
          cancelButtonText: '取消',
          type: 'warning',
        }
      )
      const response = await fetch(`${API_BASE_URL}/api/episode-renamer/logs/clear-all`, {
        method: 'DELETE',
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '清理失败')
      showMessage('success', data.message)
      await fetchLogs()
    } catch (error) {
      if (error !== 'cancel') {
        showMessage('error', error.message)
      }
    }
  }

  async function applyToCloudDrive(selectedLogs) {
    if (selectedLogs.length === 0) {
      showMessage('warning', '请至少选择一个项目进行应用。')
      return
    }
    isApplying.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/episode-renamer/apply-clouddrive-rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(selectedLogs),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动任务失败')
      showMessage('success', data.message)
    } catch (error) {
      showMessage('error', error.message)
    } finally {
      isApplying.value = false
    }
  }

  async function searchMedia(query) {
    if (!query) {
      showMessage('warning', '请输入搜索内容！')
      return
    }
    isSearching.value = true
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
      searchResults.value = data.filter(item => item.Type === 'Series')
    } catch (error) {
      showMessage('error', `搜索失败: ${error.message}`)
    } finally {
      isSearching.value = false
    }
  }

  async function manualScan(seriesId) {
    isScanning.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/episode-renamer/manual-scan/${seriesId}`, {
        method: 'POST',
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动扫描任务失败')
      showMessage('success', data.message)
    } catch (error) {
      showMessage('error', error.message)
    } finally {
      isScanning.value = false
    }
  }

  return {
    isLoading,
    logs,
    isApplying,
    isSearching,
    searchResults,
    isScanning,
    fetchLogs,
    clearCompletedLogs,
    clearAllLogs, // 导出新方法
    applyToCloudDrive,
    searchMedia,
    manualScan,
  }
})