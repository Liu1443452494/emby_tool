// frontend/src/stores/actorRoleMapper.js (完整文件覆盖)

import { ref, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';

export const useActorRoleMapperStore = defineStore('actorRoleMapper', () => {
  // --- State ---
  const isLoading = ref(false);
  const isSavingItem = ref({});
  
  // 原始的、完整的映射表数据
  const fullActorMap = ref([]);
  
  // --- 新增：用于分页懒加载的状态 ---
  const displayedActorMap = ref([]); // 当前在页面上显示的列表
  const itemsPerLoad = 30; // 每次加载的数量
  const isFullyLoaded = ref(false); // 是否已全部加载完毕
  const totalMapCount = computed(() => fullActorMap.value.length);
  // --- 新增结束 ---

// frontend/src/stores/actorRoleMapper.js (函数替换)

  async function fetchMap() {
    isLoading.value = true;
    fullActorMap.value = [];
    displayedActorMap.value = [];
    isFullyLoaded.value = false;
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/map`);
      if (response.status === 404) {
        ElMessage.info('本地不存在 actor_role_map.json 文件。');
        return;
      }
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '获取映射表失败');
      }
      const data = await response.json();
      
      // --- 核心修改 1: 将 tmdb_id 重命名为 map_key ---
      fullActorMap.value = Object.entries(data).map(([map_key, value]) => ({
        map_key,
        ...value
      })).sort((a, b) => a.title.localeCompare(b.title));

      displayedActorMap.value = fullActorMap.value.slice(0, itemsPerLoad);
      
      if (displayedActorMap.value.length >= fullActorMap.value.length) {
        isFullyLoaded.value = true;
      }

    } catch (error) {
      ElMessage.error(error.message);
    } finally {
      isLoading.value = false;
    }
  }// frontend/src/stores/actorRoleMapper.js (函数替换)

  async function fetchMap() {
    isLoading.value = true;
    fullActorMap.value = [];
    displayedActorMap.value = [];
    isFullyLoaded.value = false;
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/map`);
      if (response.status === 404) {
        ElMessage.info('本地不存在 actor_role_map.json 文件。');
        return;
      }
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '获取映射表失败');
      }
      const data = await response.json();
      
      // --- 核心修改 1: 将 tmdb_id 重命名为 map_key ---
      fullActorMap.value = Object.entries(data).map(([map_key, value]) => ({
        map_key,
        ...value
      })).sort((a, b) => a.title.localeCompare(b.title));

      displayedActorMap.value = fullActorMap.value.slice(0, itemsPerLoad);
      
      if (displayedActorMap.value.length >= fullActorMap.value.length) {
        isFullyLoaded.value = true;
      }

    } catch (error) {
      ElMessage.error(error.message);
    } finally {
      isLoading.value = false;
    }
  }

  // --- 新增：加载更多数据的 action ---
  function loadMore() {
    if (isLoading.value || isFullyLoaded.value) return;

    const currentLength = displayedActorMap.value.length;
    const nextItems = fullActorMap.value.slice(currentLength, currentLength + itemsPerLoad);
    
    if (nextItems.length > 0) {
      displayedActorMap.value.push(...nextItems);
    }

    if (displayedActorMap.value.length >= fullActorMap.value.length) {
      isFullyLoaded.value = true;
    }
  }
  // --- 新增结束 ---

  async function startTask(endpoint, payload) {
    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动任务失败');
      ElMessage.success(data.message);
    } catch (error) {
      if (error.message && error.message.includes('启动任务失败')) {
        ElMessage.error(`操作失败: ${error.message}`);
      }
    }
  }

  async function startSingleRestore(mapData) {
    try {
      await ElMessageBox.confirm(
        `即将根据当前映射关系，恢复作品《${mapData.title}》在 Emby 中的演员角色名。此操作会直接修改您的 Emby 数据。是否继续？`,
        '确认恢复操作',
        {
          confirmButtonText: '确定恢复',
          cancelButtonText: '取消',
          type: 'info',
        }
      );
      
      const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/restore-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ map_data: mapData }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动任务失败');
      ElMessage.success(data.message);

    } catch (error) {
      if (error !== 'cancel') {
        ElMessage.error(`操作失败: ${error.message}`);
      }
    }
  }


  async function saveMapChanges(mapData) {
    // --- 核心修改 1: 使用 map_key 作为 loading 状态的键 ---
    isSavingItem.value[mapData.map_key] = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/update-single-map`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ map_data: mapData }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存失败');
      
      const index = fullActorMap.value.findIndex(item => item.map_key === mapData.map_key);
      if (index !== -1) {
        fullActorMap.value[index] = { ...fullActorMap.value[index], ...mapData };
      }

      ElMessage.success(data.message);
      return true;
    } catch (error) {
      ElMessage.error(`保存失败: ${error.message}`);
      return false;
    } finally {
      isSavingItem.value[mapData.map_key] = false;
    }
  }

  return {
    isLoading,
    isSavingItem,
    fullActorMap,
    displayedActorMap,
    isFullyLoaded,
    totalMapCount,
    fetchMap,
    loadMore,
    startTask,
    startSingleRestore,
    saveMapChanges,
  };
});