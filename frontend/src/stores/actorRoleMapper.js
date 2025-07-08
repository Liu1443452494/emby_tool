// frontend/src/stores/actorRoleMapper.js (新文件)

import { ref, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';

export const useActorRoleMapperStore = defineStore('actorRoleMapper', () => {
  const isLoading = ref(false);
  const actorMap = ref([]); // 原始数据将是对象，转换为数组以便v-for
  const isSavingItem = ref({});

  async function fetchMap() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/map`);
      if (response.status === 404) {
        actorMap.value = [];
        ElMessage.info('本地不存在 actor_role_map.json 文件。');
        return;
      }
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '获取映射表失败');
      }
      const data = await response.json();
      // 将对象转换为数组以便于排序和 v-for
      actorMap.value = Object.entries(data).map(([tmdb_id, value]) => ({
        tmdb_id,
        ...value
      })).sort((a, b) => a.title.localeCompare(b.title));

    } catch (error) {
      ElMessage.error(error.message);
      actorMap.value = [];
    } finally {
      isLoading.value = false;
    }
  }

// frontend/src/stores/actorRoleMapper.js (函数替换)

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
      // 只有在不是用户取消操作时才显示错误
      if (error.message && error.message.includes('启动任务失败')) {
        ElMessage.error(`操作失败: ${error.message}`);
      }
      // 不再重新抛出错误，以避免在控制台看到不必要的 "Uncaught (in promise)"
    }
  }

  // frontend/src/stores/actorRoleMapper.js (新增函数)

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
    // --- 修改：在 action 内部管理加载状态 ---
    isSavingItem.value[mapData.tmdb_id] = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-role-mapper/update-single-map`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ map_data: mapData }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存失败');
      ElMessage.success(data.message);
      return true;
    } catch (error) {
      ElMessage.error(`保存失败: ${error.message}`);
      return false;
    } finally {
      // --- 修改：在 action 内部结束加载状态 ---
      isSavingItem.value[mapData.tmdb_id] = false;
    }
  }
  return {
    isLoading,
    actorMap,
    isSavingItem,
    fetchMap,
    startTask,
    startSingleRestore,
    saveMapChanges,
  };
});