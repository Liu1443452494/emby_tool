// ❗ 注意：以下是 frontend/src/stores/upcoming.js 文件的完整文件代码，请直接覆盖整个文件内容。

import { ref, reactive } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';
import { GENRE_MAP, COUNTRY_MAP, LANGUAGE_MAP, mapToOptions } from '@/config/filterConstants';

export const useUpcomingStore = defineStore('upcoming', () => {
  // --- State ---
  const config = ref({
    enabled: true,
    notification_cron: '0 9 * * *',
    filters: {
      fetch_days: 1,
      genre_blacklist: [],
      p0_countries: [],
      p0_languages: [],
      p1_countries: [],
    }
  });

  const filterOptions = reactive({
    fetch_days: 1,
    genre_blacklist: { available: [], selected: [], builtIn: [] },
    p0_countries: { available: [], selected: [], builtIn: [] },
    p0_languages: { available: [], selected: [], builtIn: [] },
    p1_countries: { available: [], selected: [], builtIn: [] },
  });
  
  const upcomingList = ref([]);
  const subscriptions = ref({});
  const isLoading = ref(false);
  const isListLoading = ref(false);
  const isSaving = ref(false);

  // --- Actions ---
  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };



  function _buildFilterOptions(defaultFilters) {
    const build = (key, sourceMap) => {
      const defaults = defaultFilters[key] || [];
      const options = mapToOptions(sourceMap);

      // --- 新增：排序逻辑 ---
      // 1. 先按是否为内置项排序 (内置的在前)
      // 2. 在相同类别内，按标签的字母顺序排序
      options.sort((a, b) => {
        const isABuiltIn = defaults.includes(a.value);
        const isBBuiltIn = defaults.includes(b.value);
        if (isABuiltIn && !isBBuiltIn) return -1;
        if (!isABuiltIn && isBBuiltIn) return 1;
        return a.label.localeCompare(b.label, 'zh-CN');
      });
      // --- 新增结束 ---

      filterOptions[key] = {
        available: options,
        selected: [...defaults],
        builtIn: [...defaults],
      };
    };
    
    filterOptions.fetch_days = defaultFilters.fetch_days;
    build('genre_blacklist', GENRE_MAP);
    build('p0_countries', COUNTRY_MAP);
    build('p0_languages', LANGUAGE_MAP);
    build('p1_countries', COUNTRY_MAP);
  }
  async function fetchConfig() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/upcoming/config`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取配置失败');
      config.value = data;
      _buildFilterOptions(data.filters);
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isLoading.value = false;
    }
  }

  async function saveConfig(newConfig) {
    isSaving.value = true;
    try {
      // 从 filterOptions 中提取纯数组配置进行保存
      const configToSave = {
        ...newConfig,
        filters: {
          fetch_days: filterOptions.fetch_days,
          genre_blacklist: filterOptions.genre_blacklist.selected,
          p0_countries: filterOptions.p0_countries.selected,
          p0_languages: filterOptions.p0_languages.selected,
          p1_countries: filterOptions.p1_countries.selected,
        }
      };

      const response = await fetch(`${API_BASE_URL}/api/upcoming/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configToSave),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存配置失败');
      showMessage('success', data.message);
      await fetchConfig();
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  async function fetchUpcomingList(useDefaults = false) {
    isListLoading.value = true;
    upcomingList.value = [];
    try {
      let payload = {};
      if (useDefaults) {
        payload = { use_defaults: true };
      } else {
        payload = {
          fetch_days: filterOptions.fetch_days,
          genre_blacklist: filterOptions.genre_blacklist.selected,
          p0_countries: filterOptions.p0_countries.selected,
          p0_languages: filterOptions.p0_languages.selected,
          p1_countries: filterOptions.p1_countries.selected,
          use_defaults: false,
        };
      }

      const response = await fetch(`${API_BASE_URL}/api/upcoming/list`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取列表失败');
      upcomingList.value = data;
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isListLoading.value = false;
    }
  }

  async function fetchSubscriptions() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/upcoming/subscriptions`);
      if (!response.ok) throw new Error('获取订阅列表失败');
      subscriptions.value = await response.json();
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  async function subscribeItem(item) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/upcoming/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(item),
      });
      if (!response.ok) throw new Error('订阅失败');
      showMessage('success', `《${item.title}》已成功订阅！`);
      await fetchSubscriptions();
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    }
  }

  async function unsubscribeItem(item) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/upcoming/unsubscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tmdb_id: item.tmdb_id }),
      });
      if (!response.ok) throw new Error('取消订阅失败');
      showMessage('success', `已取消对《${item.title}》的订阅。`);
      await fetchSubscriptions();
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  function resetFilters() {
    for (const key in filterOptions) {
      if (typeof filterOptions[key] === 'object' && filterOptions[key] !== null && 'builtIn' in filterOptions[key]) {
        filterOptions[key].selected = [...filterOptions[key].builtIn];
      }
    }
    filterOptions.fetch_days = config.value.filters.fetch_days;
    showMessage('info', '筛选条件已重置为默认值，请点击“应用筛选”或“保存设置”以生效。');
  }

  return {
    config,
    filterOptions,
    upcomingList,
    subscriptions,
    isLoading,
    isListLoading,
    isSaving,
    fetchConfig,
    saveConfig,
    fetchUpcomingList,
    fetchSubscriptions,
    subscribeItem,
    unsubscribeItem,
    resetFilters,
  };
});