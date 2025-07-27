// frontend/src/stores/upcoming.js (完整文件覆盖)

import { ref, reactive, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';
import { GENRE_MAP, COUNTRY_MAP, LANGUAGE_MAP, mapToOptions } from '@/config/filterConstants';
import _ from 'lodash';

export const useUpcomingStore = defineStore('upcoming', () => {
  // --- State ---
  const config = ref({
    enabled: true,
    notification_cron: '0 9 * * *',
    pruning_cron: '0 1 * * *',
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
  
  const allData = ref([]);
  const isLoading = ref(false);
  const isListLoading = ref(false);
  const isSaving = ref(false);
  
  // --- 新增：用于检查配置是否变更的快照 ---
  let filterSnapshot = null;

  // --- Computed ---
  const upcomingMovies = computed(() => allData.value.filter(item => item.media_type === 'movie'));
  const upcomingTvs = computed(() => allData.value.filter(item => item.media_type === 'tv'));
  const subscriptionList = computed(() => allData.value.filter(item => item.is_subscribed).sort((a, b) => a.release_date.localeCompare(b.release_date)));

  // --- Actions ---
  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };

  function _buildFilterOptions(defaultFilters) {
    const build = (key, sourceMap) => {
      const defaults = defaultFilters[key] || [];
      const options = mapToOptions(sourceMap);
      options.sort((a, b) => {
        const isABuiltIn = defaults.includes(a.value);
        const isBBuiltIn = defaults.includes(b.value);
        if (isABuiltIn && !isBBuiltIn) return -1;
        if (!isABuiltIn && isBBuiltIn) return 1;
        return a.label.localeCompare(b.label, 'zh-CN');
      });
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
    
    // 创建初始快照
    filterSnapshot = _.cloneDeep(filterOptions);
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
      await fetchConfig(); // 重新获取配置以更新快照
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  async function fetchUpcomingList(useDefaults = false) {
    // 检查配置是否变更
    if (!useDefaults && _.isEqual(filterOptions, filterSnapshot)) {
      showMessage('info', '筛选条件未发生变化，已跳过刷新。');
      return;
    }

    isListLoading.value = true;
    allData.value = [];
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
      allData.value = data;
      
      // 强制刷新后，更新快照
      if (!useDefaults) {
        filterSnapshot = _.cloneDeep(filterOptions);
      }
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isListLoading.value = false;
    }
  }

  async function fetchAllData() {
    console.log("fetchAllData: 正在从后端获取本地数据库内容...");
    try {
      const response = await fetch(`${API_BASE_URL}/api/upcoming/data`);
      if (!response.ok) throw new Error('获取数据失败');
      allData.value = await response.json();
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  async function updateSubscription(item, subscribe) {
    const action = subscribe ? 'subscribe' : 'unsubscribe';
    try {
      const response = await fetch(`${API_BASE_URL}/api/upcoming/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tmdb_id: item.tmdb_id }),
      });
      if (!response.ok) throw new Error(`${subscribe ? '订阅' : '取消订阅'}失败`);
      
      // 本地乐观更新
      const targetItem = allData.value.find(i => i.tmdb_id === item.tmdb_id);
      if (targetItem) {
        targetItem.is_subscribed = subscribe;
      }
      
      showMessage('success', `操作成功！`);
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
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
    allData,
    upcomingMovies,
    upcomingTvs,
    subscriptionList,
    isLoading,
    isListLoading,
    isSaving,
    fetchConfig,
    saveConfig,
    fetchUpcomingList,
    fetchAllData,
    updateSubscription,
    resetFilters,
  };
});