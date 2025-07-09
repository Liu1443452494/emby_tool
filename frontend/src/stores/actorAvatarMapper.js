// frontend/src/stores/actorAvatarMapper.js (新文件)

import { ref, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { API_BASE_URL, TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';

export const useActorAvatarMapperStore = defineStore('actorAvatarMapper', () => {
  const isLoading = ref(false);
  const avatarMap = ref([]); // 原始数据是对象，将转换为数组

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };

  const sortedAvatarMap = computed(() => {
    return avatarMap.value.sort((a, b) => a.actor_name.localeCompare(b.actor_name, 'zh-CN'));
  });

  async function fetchMap() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-avatar-mapper/map`);
      if (response.status === 404) {
        avatarMap.value = [];
        showMessage('info', '本地不存在演员头像映射文件。');
        return;
      }
      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '获取头像映射表失败');
      }
      const data = await response.json();
      // 将对象转换为数组以便于排序和 v-for
      avatarMap.value = Object.entries(data).map(([tmdb_id, value]) => ({
        tmdb_id,
        ...value
      }));
    } catch (error) {
      showMessage('error', error.message);
      avatarMap.value = [];
    } finally {
      isLoading.value = false;
    }
  }

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
    // 对于豆瓣，image_path 已经是完整 URL，但为了安全，我们通过后端代理访问
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
    avatarMap,
    sortedAvatarMap,
    fetchMap,
    startTask,
    getFullImageUrl,
    startSingleRestore,
  };
});