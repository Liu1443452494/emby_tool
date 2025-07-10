// frontend/src/stores/log.js (完整文件覆盖)
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE_URL, WS_BASE_URL } from '@/config/apiConfig';
import { useStorage } from '@vueuse/core';

export const useLogStore = defineStore('log', () => {
  const logs = ref([])
  const totalLogs = ref(0)
  const currentPage = ref(1)
  const isConnected = ref(false)
  const logLevel = ref('INFO')
  const pageSize = useStorage('log-page-size', 1000); 
  let ws = null
  let reconnectTimer = null

  const totalPages = computed(() => Math.ceil(totalLogs.value / pageSize.value))

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  async function fetchHistoricalLogs(page = 1) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/logs?page=${page}&page_size=${pageSize.value}&level=${logLevel.value}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '获取历史日志失败')
      
      // --- 核心修改：不再需要添加 id ---
      logs.value = data.logs
      // --- 修改结束 ---
      
      totalLogs.value = data.total
      currentPage.value = page
    } catch (error) {
      showMessage('error', `获取历史日志失败: ${error.message}`)
    }
  }

  async function setLogLevelAndFetch(newLevel) {
    logLevel.value = newLevel;
    await fetchHistoricalLogs(1);
  }

  async function setPageSizeAndFetch(newPageSize) {
    pageSize.value = newPageSize;
    await fetchHistoricalLogs(1); 
  }

    function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    ws = new WebSocket(`${WS_BASE_URL}/ws/logs`)
    ws.onopen = () => {
      isConnected.value = true
      console.log("日志 WebSocket 已连接")
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    }
    ws.onmessage = (event) => {
      const logData = JSON.parse(event.data)
      
      const currentLevel = logLevel.value.toUpperCase();
      const logItemLevel = logData.level.toUpperCase();
      
      const isVisibleAtCurrentLevel = currentLevel === 'ALL' || logItemLevel === currentLevel;
      
      if (isVisibleAtCurrentLevel) {
        totalLogs.value++;

        if (currentPage.value === 1) {
          // --- 核心修改：不再需要添加 id ---
          logs.value.unshift(logData);
          // --- 修改结束 ---
          if (logs.value.length > pageSize.value) {
            logs.value.pop();
          }
        }
      }
    }
    ws.onclose = () => {
      isConnected.value = false
      console.log("日志 WebSocket 已断开")
      if (!reconnectTimer) { reconnectTimer = setTimeout(() => connect(), 5000) }
    }
    ws.onerror = (error) => { isConnected.value = false; console.error("日志 WebSocket 错误:", error) }
  }

  function disconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (ws) { ws.onclose = null; ws.close(); ws = null; isConnected.value = false; console.log("日志 WebSocket 已手动断开") }
  }

  async function clearLogs() {
    try {
      await ElMessageBox.confirm(
        '确定要清空所有日志吗？此操作不可恢复。',
        '警告',
        { confirmButtonText: '确定清空', cancelButtonText: '取消', type: 'warning' }
      )
      
      const response = await fetch(`${API_BASE_URL}/api/logs`, { method: 'DELETE' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '清空失败')
      
      logs.value = []
      totalLogs.value = 0
      currentPage.value = 1
      showMessage('success', '日志已成功清空！')
    } catch (error) {
      if (error !== 'cancel') { 
        showMessage('error', `清空日志失败: ${error.message}`) 
      }
    }
  }

  return { 
    logs, totalLogs, currentPage, totalPages, isConnected, logLevel, pageSize,
    fetchHistoricalLogs, connect, disconnect, clearLogs, setLogLevelAndFetch,
    setPageSizeAndFetch
  }
})