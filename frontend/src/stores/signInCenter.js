// frontend/src/stores/signInCenter.js (新文件)

import { ref, reactive } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useConfigStore } from './config';
import { API_BASE_URL } from '@/config/apiConfig';
import _ from 'lodash';

export const useSignInCenterStore = defineStore('signInCenter', () => {
  // --- State ---
  const modules = ref([]);
  const isLoading = ref(false);
  const isSaving = ref(false);
  const configStore = useConfigStore();
  // 用于存储各个模块的独立数据
  const historyData = reactive({});
  const logData = reactive({});
  const isHistoryLoading = ref(false);
  const isLogLoading = ref(false);

  // --- Actions ---
  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };

  async function fetchModules() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/signin/modules`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取签到模块列表失败');
      modules.value = data;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isLoading.value = false;
    }
  }

  // frontend/src/stores/signInCenter.js (函数替换)

  async function saveConfig(moduleId, configToSave) {
    isSaving.value = true;
    try {
      // 找到当前 appConfig 中的签到配置
      const fullSigninConfig = _.cloneDeep(configStore.appConfig.signin_config) || {};
      // 更新指定模块的配置
      fullSigninConfig[moduleId] = configToSave;

      const response = await fetch(`${API_BASE_URL}/api/signin/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fullSigninConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存配置失败');
      showMessage('success', data.message);
      
      // 更新本地 Pinia 状态，避免重新请求
      const moduleIndex = modules.value.findIndex(m => m.id === moduleId);
      if (moduleIndex !== -1) {
        modules.value[moduleIndex].config = configToSave;
      }
      
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  async function triggerSignIn(moduleId) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/signin/${moduleId}/trigger`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '触发签到失败');
      showMessage('success', data.message);
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  async function fetchHistory(moduleId) {
    isHistoryLoading.value = true;
    historyData[moduleId] = [];
    try {
      const response = await fetch(`${API_BASE_URL}/api/signin/${moduleId}/history`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取历史记录失败');
      historyData[moduleId] = data;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isHistoryLoading.value = false;
    }
  }

  async function fetchLogs(moduleId, moduleName) {
    isLogLoading.value = true;
    logData[moduleId] = [];
    try {
      const category = `签到-${moduleName}`;
      const response = await fetch(`${API_BASE_URL}/api/logs?page=1&page_size=500&level=ALL&category=${encodeURIComponent(category)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取日志失败');
      logData[moduleId] = data.logs;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isLogLoading.value = false;
    }
  }

  async function resetData(moduleId, moduleName) {
    try {
      await ElMessageBox.confirm(
        `确定要重置【${moduleName}】的所有统计数据吗？此操作将清空连续签到天数等信息，但会保留历史记录。`,
        '警告',
        {
          confirmButtonText: '确定重置',
          cancelButtonText: '取消',
          type: 'warning',
        }
      );
      const response = await fetch(`${API_BASE_URL}/api/signin/${moduleId}/reset-data`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '重置失败');
      showMessage('success', data.message);
      await fetchModules(); // 重置后刷新状态
    } catch (error) {
      if (error !== 'cancel') {
        showMessage('error', error.message);
      }
    }
  }

  return {
    modules,
    isLoading,
    isSaving,
    historyData,
    logData,
    isHistoryLoading,
    isLogLoading,
    fetchModules,
    saveConfig,
    triggerSignIn,
    fetchHistory,
    fetchLogs,
    resetData,
  };
});