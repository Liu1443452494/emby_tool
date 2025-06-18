// frontend/src/stores/doubanFixer.js (完整代码)

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig'

export const useDoubanFixerStore = defineStore('doubanFixer', () => {
  const isLoading = ref(false)
  const isScanning = ref(false)
  const cachedItems = ref([])
  const isSearching = ref(false)
  const isUpdating = ref(false)
  const searchResults = ref([])

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  // 获取失败缓存列表
  async function fetchCachedItems() {
    isLoading.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/douban-fixer/cache`)
      if (!response.ok) {
        const err = await response.json()
        throw new Error(err.detail || '获取缓存列表失败')
      }
      cachedItems.value = await response.json()
    } catch (error) {
      showMessage('error', error.message)
      cachedItems.value = []
    } finally {
      isLoading.value = false
    }
  }

  // 触发全量扫描
  async function startFullScan(payload) {
    isScanning.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/douban-fixer/scan-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || '启动扫描任务失败')
      }
      showMessage('success', data.message)
    } catch (error) {
      showMessage('error', error.message)
    } finally {
      isScanning.value = false
    }
  }

  // 清空缓存
  async function clearCache() {
    try {
      await ElMessageBox.confirm(
        '确定要清空所有匹配失败的缓存吗？此操作不可恢复。',
        '警告',
        {
          confirmButtonText: '确定清空',
          cancelButtonText: '取消',
          type: 'warning',
        }
      )
      
      const response = await fetch(`${API_BASE_URL}/api/douban-fixer/cache`, {
        method: 'DELETE',
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || '清空缓存失败')
      }
      showMessage('success', data.message)
      await fetchCachedItems() // 刷新列表
    } catch (error) {
      if (error !== 'cancel') {
        showMessage('error', error.message)
      }
    }
  }

  // 手动搜索
  async function manualSearch(name) {
    isSearching.value = true
    searchResults.value = []
    try {
      const response = await fetch(`${API_BASE_URL}/api/douban-fixer/manual-search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || '搜索失败')
      }
      if (data.length === 0) {
        showMessage('info', '没有找到相关的豆瓣条目。')
      }
      searchResults.value = data
    } catch (error) {
      showMessage('error', error.message)
    } finally {
      isSearching.value = false
    }
  }

  // 手动更新
  async function manualUpdate(embyItemId, doubanId) {
    isUpdating.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/douban-fixer/manual-update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emby_item_id: embyItemId, douban_id: doubanId }),
      })
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || '更新失败')
      }
      showMessage('success', data.message)
      // 从前端缓存列表中移除该项
      cachedItems.value = cachedItems.value.filter(item => item.Id !== embyItemId)
      return true
    } catch (error) {
      showMessage('error', error.message)
      return false
    } finally {
      isUpdating.value = false
    }
  }

  return {
    isLoading,
    isScanning,
    cachedItems,
    isSearching,
    isUpdating,
    searchResults,
    fetchCachedItems,
    startFullScan,
    clearCache,
    manualSearch,
    manualUpdate,
  }
})