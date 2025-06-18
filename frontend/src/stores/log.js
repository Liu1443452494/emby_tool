// frontend/src/stores/log.js (修改后)
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage, ElMessageBox } from 'element-plus'
import { API_BASE_URL, WS_BASE_URL } from '@/config/apiConfig';

const PAGE_SIZE = 100;

export const useLogStore = defineStore('log', () => {
  const logs = ref([])
  const totalLogs = ref(0)
  const currentPage = ref(1)
  const isConnected = ref(false)
  let ws = null
  let reconnectTimer = null

  const totalPages = computed(() => Math.ceil(totalLogs.value / PAGE_SIZE))

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  async function fetchHistoricalLogs(page = 1) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/logs?page=${page}&page_size=${PAGE_SIZE}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '获取历史日志失败')
      
      logs.value = data.logs
      totalLogs.value = data.total
      currentPage.value = page
    } catch (error) {
      showMessage('error', `获取历史日志失败: ${error.message}`)
    }
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
      const formattedLog = `${logData.timestamp} - ${logData.name} - ${logData.level} - ${logData.message}`
      // 只在用户正在查看第一页时，才将新日志实时推送到顶部
      if (currentPage.value === 1) {
        logs.value.unshift(formattedLog)
        // 保持页面大小，移除最旧的一条日志
        if (logs.value.length > PAGE_SIZE) {
          logs.value.pop()
        }
      }
      totalLogs.value++
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

  // --- 核心修复：实现真正的清空日志功能 ---
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
      
      // 清空成功后，重置前端状态
      logs.value = []
      totalLogs.value = 0
      currentPage.value = 1
      showMessage('success', '日志已成功清空！')
    } catch (error) {
      // 用户点击取消时，error 的值为 'cancel'，此时不显示错误消息
      if (error !== 'cancel') { 
        showMessage('error', `清空日志失败: ${error.message}`) 
      }
    }
  }

  return { 
    logs, totalLogs, currentPage, totalPages, isConnected, 
    fetchHistoricalLogs, connect, disconnect, clearLogs 
  }
})