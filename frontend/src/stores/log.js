// frontend/src/stores/log.js (完整文件覆盖)
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
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

  const logCategories = ref([])
  const selectedCategory = ref('')
  
  const availableDates = ref([])
  const selectedDate = ref(null)
  const searchKeyword = ref('');

  const totalPages = computed(() => Math.ceil(totalLogs.value / pageSize.value))

  // --- 核心修改：移除 ElMessage 的直接依赖 ---
  // showMessage 函数将在组件中通过 useMessage 实现
  
  async function fetchHistoricalLogs(page = 1, options = {}) {
    const { showMessage } = options;
    try {
      let url = `${API_BASE_URL}/api/logs?page=${page}&page_size=${pageSize.value}&level=${logLevel.value}`;
      if (selectedCategory.value) {
        url += `&category=${encodeURIComponent(selectedCategory.value)}`;
      }
      if (selectedDate.value) {
        url += `&date=${selectedDate.value}`;
      }
      
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取历史日志失败');
      
      logs.value = data.logs;
      totalLogs.value = data.total;
      currentPage.value = data.currentPage;
    } catch (error) {
      if (showMessage) showMessage('error', `获取历史日志失败: ${error.message}`);
    }
  }

  async function fetchLogDates(options = {}) {
    const { showMessage } = options;
    try {
      const response = await fetch(`${API_BASE_URL}/api/logs/dates`);
      if (!response.ok) throw new Error('获取日志日期列表失败');
      availableDates.value = await response.json();
      selectedDate.value = null;
    } catch (error) {
      if (showMessage) showMessage('error', `获取日期失败: ${error.message}`);
    }
  }

  async function fetchLogCategories(options = {}) {
    const { showMessage } = options;
    try {
      const response = await fetch(`${API_BASE_URL}/api/logs/categories`);
      if (!response.ok) throw new Error('获取日志类别列表失败');
      logCategories.value = await response.json();
    } catch (error) {
      if (showMessage) showMessage('error', `获取类别失败: ${error.message}`);
    }
  }

  async function setLogLevelAndFetch(newLevel, options) {
    logLevel.value = newLevel;
    await fetchHistoricalLogs(1, options);
  }

  async function setCategoryAndFetch(newCategory, options) {
    selectedCategory.value = newCategory || '';
    await fetchHistoricalLogs(1, options);
  }

  async function setDateAndFetch(newDate, options) {
    const getTodayString = () => {
      const today = new Date();
      const yyyy = today.getFullYear();
      const mm = String(today.getMonth() + 1).padStart(2, '0');
      const dd = String(today.getDate()).padStart(2, '0');
      return `${yyyy}-${mm}-${dd}`;
    };

    if (!newDate || newDate === getTodayString()) {
      selectedDate.value = null;
    } else {
      selectedDate.value = newDate;
    }
    
    await fetchHistoricalLogs(1, options);
  }

  async function setPageSizeAndFetch(newPageSize, options) {
    pageSize.value = newPageSize;
    await fetchHistoricalLogs(1, options); 
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    ws = new WebSocket(`${WS_BASE_URL}/ws/logs`)
    ws.onopen = () => {
      isConnected.value = true
      console.log("✅ 日志 WebSocket 已连接")
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    }
    ws.onmessage = (event) => {
      const logData = JSON.parse(event.data)
      
      if (selectedDate.value !== null) {
        return;
      }

      const currentLevel = logLevel.value.toUpperCase();
      const logItemLevel = logData.level.toUpperCase();
      
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
    }
    ws.onclose = () => {
      isConnected.value = false
      console.log("⚠️ 日志 WebSocket 已断开，5秒后尝试重连...")
      if (!reconnectTimer) { reconnectTimer = setTimeout(() => connect(), 5000) }
    }
    ws.onerror = (error) => { isConnected.value = false; console.error("❌ 日志 WebSocket 错误:", error) }
  }

  function disconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (ws) { ws.onclose = null; ws.close(); ws = null; isConnected.value = false; console.log("🔌 日志 WebSocket 已手动断开") }
  }

  async function clearLogs(options = {}) {
    const { showMessage } = options;
    try {
      const response = await fetch(`${API_BASE_URL}/api/logs`, { method: 'DELETE' })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '清空失败')
      
      await fetchLogDates(options);
      await fetchLogCategories(options);
      await fetchHistoricalLogs(1, options);

      if (showMessage) showMessage('success', '所有日志已成功清空！')
      return true;
    } catch (error) {
      if (showMessage) showMessage('error', `清空日志失败: ${error.message}`) 
      return false;
    }
  }

  return { 
    logs, totalLogs, currentPage, totalPages, isConnected, logLevel, pageSize,
    logCategories, selectedCategory,
    availableDates, selectedDate,
    searchKeyword,
    fetchHistoricalLogs, connect, disconnect, clearLogs, setLogLevelAndFetch,
    setPageSizeAndFetch,
    fetchLogCategories, setCategoryAndFetch,
    fetchLogDates, setDateAndFetch
  }
})