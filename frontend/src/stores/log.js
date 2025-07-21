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

  // --- 新增：类别过滤相关状态 ---
  const logCategories = ref([])
  const selectedCategory = ref('')
  // --- 新增结束 ---

  const totalPages = computed(() => Math.ceil(totalLogs.value / pageSize.value))

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  // --- 修改：fetchHistoricalLogs 函数，增加 category 参数 ---
  async function fetchHistoricalLogs(page = 1) {
    try {
      let url = `${API_BASE_URL}/api/logs?page=${page}&page_size=${pageSize.value}&level=${logLevel.value}`;
      if (selectedCategory.value) {
        url += `&category=${encodeURIComponent(selectedCategory.value)}`;
      }
      
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取历史日志失败');
      
      logs.value = data.logs;
      totalLogs.value = data.total;
      currentPage.value = page;
    } catch (error) {
      showMessage('error', `获取历史日志失败: ${error.message}`);
    }
  }
  // --- 修改结束 ---

  // --- 新增：获取所有日志类别 ---
  async function fetchLogCategories() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/logs/categories`);
      if (!response.ok) throw new Error('获取日志类别列表失败');
      logCategories.value = await response.json();
    } catch (error) {
      showMessage('error', `获取类别失败: ${error.message}`);
    }
  }
  // --- 新增结束 ---

  async function setLogLevelAndFetch(newLevel) {
    logLevel.value = newLevel;
    await fetchHistoricalLogs(1);
  }

  // --- 新增：设置类别并重新获取日志 ---
  async function setCategoryAndFetch(newCategory) {
    selectedCategory.value = newCategory || ''; // 如果传入 null 或 undefined，则重置为空字符串
    await fetchHistoricalLogs(1);
  }
  // --- 新增结束 ---

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
      
      // --- 修改：增加类别匹配逻辑 ---
      const categoryMatches = !selectedCategory.value || logData.category === selectedCategory.value;
      const levelMatches = currentLevel === 'ALL' || logItemLevel === currentLevel;
      
      if (levelMatches && categoryMatches) {
        totalLogs.value++;

        if (currentPage.value === 1) {
          logs.value.unshift(logData);
          if (logs.value.length > pageSize.value) {
            logs.value.pop();
          }
        }
      }
      // --- 修改结束 ---
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
      // --- 新增：清空日志后也要刷新类别列表 ---
      await fetchLogCategories();
      // --- 新增结束 ---
      showMessage('success', '日志已成功清空！')
    } catch (error) {
      if (error !== 'cancel') { 
        showMessage('error', `清空日志失败: ${error.message}`) 
      }
    }
  }

  return { 
    logs, totalLogs, currentPage, totalPages, isConnected, logLevel, pageSize,
    logCategories, selectedCategory, // 导出新状态
    fetchHistoricalLogs, connect, disconnect, clearLogs, setLogLevelAndFetch,
    setPageSizeAndFetch,
    fetchLogCategories, setCategoryAndFetch // 导出新方法
  }
})