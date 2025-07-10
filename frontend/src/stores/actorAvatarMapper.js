// frontend/src/stores/actorAvatarMapper.js (完整文件覆盖)

import { ref, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { API_BASE_URL, TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';

export const useActorAvatarMapperStore = defineStore('actorAvatarMapper', () => {
  // --- State ---
  const isLoading = ref(false);
  const fullAvatarMap = ref([]); // 原始的、完整的映射表数据
  
  // --- 新增：用于分页懒加载的状态 ---
  const displayedAvatarMap = ref([]); // 当前在页面上显示的列表
  const itemsPerLoad = 10; // 每次加载的数量
  const isFullyLoaded = ref(false); // 是否已全部加载完毕
  const totalMapCount = computed(() => fullAvatarMap.value.length);
  // --- 新增结束 ---

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };

  // --- 修改：sortedAvatarMap 现在基于 displayedAvatarMap ---
  const sortedAvatarMap = computed(() => {
    // 注意：这里的排序只对当前已显示的列表生效，如果需要全局排序，应在 fetchMap 中对 fullAvatarMap 排序
    return displayedAvatarMap.value.slice().sort((a, b) => a.actor_name.localeCompare(b.actor_name, 'zh-CN'));
  });
  // --- 修改结束 ---

  async function fetchMap() {
    isLoading.value = true;
    // 重置所有状态
    fullAvatarMap.value = [];
    displayedAvatarMap.value = [];
    isFullyLoaded.value = false;
    

    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-avatar-mapper/map`);
      if (response.status === 404) {
        ElMessage.info('本地不存在演员头像映射文件。');
        return;
      }
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '获取头像映射表失败');
      }
      const data = await response.json();
      
      // 将原始数据存储在 fullAvatarMap 中，并预先排序
      fullAvatarMap.value = Object.entries(data).map(([tmdb_id, value]) => ({
        tmdb_id,
        ...value
      })).sort((a, b) => a.actor_name.localeCompare(b.actor_name, 'zh-CN'));

      // 初始化第一页显示的数据
      displayedAvatarMap.value = fullAvatarMap.value.slice(0, itemsPerLoad);
      
      if (displayedAvatarMap.value.length >= fullAvatarMap.value.length) {
        isFullyLoaded.value = true;
      }

    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isLoading.value = false;
    }
  }

  // --- 新增：加载更多数据的 action ---
  function loadMore() {
    if (isLoading.value || isFullyLoaded.value) return;

    const currentLength = displayedAvatarMap.value.length;
    const nextItems = fullAvatarMap.value.slice(currentLength, currentLength + itemsPerLoad);
    
    if (nextItems.length > 0) {
      displayedAvatarMap.value.push(...nextItems);
    }

    if (displayedAvatarMap.value.length >= fullAvatarMap.value.length) {
      isFullyLoaded.value = true;
    }
  }
  // --- 新增结束 ---

  async function startTask(endpoint, payload, confirmOptions) {
    try {
      if (confirmOptions) {
        await ElMessageBox.confirm(confirmOptions.message, confirmOptions.title, {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'info',
        });
      }
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动任务失败');
      showMessage('success', data.message);
    } catch (error) {
      if (error !== 'cancel' && error.message) {
        showMessage('error', `操作失败: ${error.message}`);
      }
    }
  }

  function getFullImageUrl(item) {
    if (!item || !item.source || !item.image_path) return '';
    if (item.source === 'tmdb') {
      return `${TMDB_IMAGE_BASE_URL}${TMDB_IMAGE_SIZES.avatar}${item.image_path}`;
    }
    return `${API_BASE_URL}/api/image-proxy?url=${encodeURIComponent(item.image_path)}`;
  }

  async function startSingleRestore(actorInfo, scope) {
    try {
      await ElMessageBox.confirm(
        `即将为演员【${actorInfo.actor_name}】恢复头像。此操作会扫描您在左侧选择的范围来寻找该演员，然后进行恢复。是否继续？`,
        '确认单体恢复',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'info',
        }
      );
      const payload = {
        actor_info: actorInfo,
        scope: scope
      };
      const response = await fetch(`${API_BASE_URL}/api/actor-avatar-mapper/restore-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动任务失败');
      showMessage('success', data.message);
    } catch (error) {
      if (error !== 'cancel' && error.message) {
        showMessage('error', `操作失败: ${error.message}`);
      }
    }
  }

  return {
    isLoading,
    fullAvatarMap,
    displayedAvatarMap,
    isFullyLoaded,
    totalMapCount,
    sortedAvatarMap,
    fetchMap,
    loadMore,
    startTask,
    getFullImageUrl,
    startSingleRestore,
  };
});