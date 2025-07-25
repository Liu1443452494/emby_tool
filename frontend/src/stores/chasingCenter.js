// frontend/src/stores/chasingCenter.js (新文件)

import { ref, reactive } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';
import _ from 'lodash';

export const useChasingCenterStore = defineStore('chasingCenter', () => {
  // --- State ---
  const config = ref({
    enabled: false,
    notification_cron: '0 9 * * *',
    calendar_days: 7,
    completion_deadline_days: 30,
  });
  const chasingList = ref([]);
  const isLoading = ref(false);
  const isListLoading = ref(false);
  const isSaving = ref(false);
  const calendarData = ref({});
  const isCalendarLoading = ref(false);

  // --- Actions ---
  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };

  async function fetchConfig() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/config`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取配置失败');
      config.value = data;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isLoading.value = false;
    }
  }

  async function saveConfig(newConfig) {
    isSaving.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存配置失败');
      showMessage('success', data.message);
      await fetchConfig(); // 保存后刷新
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  async function fetchList() {
    isListLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/list`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取列表失败');
      chasingList.value = data;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isListLoading.value = false;
    }
  }

  async function addToList(series) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_id: series.Id, series_name: series.Name }),
      });
      if (!response.ok) throw new Error('添加失败');
      showMessage('success', `《${series.Name}》已成功加入追更列表！`);
      await fetchList(); // 刷新列表
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    }
  }

  async function removeFromList(series) {
    try {
      await ElMessageBox.confirm(
        `确定要将《${series.Name}》从追更列表中移除吗？`,
        '确认移除',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning',
        }
      );
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/remove`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ series_id: series.Id, series_name: series.Name }),
      });
      if (!response.ok) throw new Error('移除失败');
      showMessage('success', `《${series.Name}》已成功移除！`);
      await fetchList(); // 刷新列表
    } catch (error) {
      if (error !== 'cancel') {
        showMessage('error', error.message);
      }
    }
  }

  async function triggerRun() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/trigger-run`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '触发失败');
      showMessage('success', data.message);
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  async function triggerCalendar() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/trigger-calendar`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '触发失败');
      showMessage('success', data.message);
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  async function fetchCalendarData(seriesId) {
    isCalendarLoading.value = true;
    calendarData.value = {};
    try {
      const response = await fetch(`${API_BASE_URL}/api/chasing-center/${seriesId}/calendar`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取日历数据失败');
      calendarData.value = data;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isCalendarLoading.value = false;
    }
  }



  return {
    config,
    chasingList,
    isLoading,
    isListLoading,
    isSaving,
    calendarData,
    isCalendarLoading,
    fetchConfig,
    saveConfig,
    fetchList,
    addToList,
    removeFromList,
    triggerRun,
    triggerCalendar,
    fetchCalendarData,
  };
});