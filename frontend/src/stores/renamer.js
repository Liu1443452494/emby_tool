import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig'

export const useRenamerStore = defineStore('renamer', () => {
  const isLoading = ref(false)
  const activeScanTaskId = ref(null)
  const renamePlan = ref([])

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  async function startScan(payload) {
    isLoading.value = true
    renamePlan.value = []
    try {
      const response = await fetch(`${API_BASE_URL}/api/renamer/scan-plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动扫描任务失败')
      
      activeScanTaskId.value = data.task_id
      showMessage('success', data.message)
      return { success: true, taskId: data.task_id }
    } catch (error) {
      showMessage('error', `操作失败: ${error.message}`)
      isLoading.value = false
      return { success: false }
    }
  }

  function setRenamePlan(plan) {
    renamePlan.value = plan
  }

  function clearActiveTask() {
    activeScanTaskId.value = null
    isLoading.value = false
  }

  return { 
    isLoading, 
    activeScanTaskId,
    renamePlan,
    startScan,
    setRenamePlan,
    clearActiveTask
  }
})