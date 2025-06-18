// frontend/src/stores/douban.js (修改后)
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
// --- 核心修改 1: 导入 API 配置 ---
import { API_BASE_URL } from '@/config/apiConfig';

export const useDoubanStore = defineStore('douban', () => {
  const isLoading = ref(false)

  const showMessage = (type, message) => {
    ElMessage({
      message: message,
      type: type,
      showClose: true,
      duration: 3000,
    })
  }

  async function forceRefresh() {
    isLoading.value = true
    try {
      // --- 核心修改 2: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/douban/force-refresh`, {
        method: 'POST',
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动刷新任务失败')
      
      showMessage('success', data.message)
      return { success: true, data }
    } catch (error) {
      showMessage('error', `操作失败: ${error.message}`)
      return { success: false, message: error.message }
    } finally {
      isLoading.value = false
    }
  }

  return { 
    isLoading, 
    forceRefresh 
  }
})