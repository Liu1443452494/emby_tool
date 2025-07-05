import { ref, computed } from 'vue';
import { defineStore } from 'pinia';
import { ElMessage, ElMessageBox } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';
import _ from 'lodash';

export const usePosterManagerStore = defineStore('posterManager', () => {
  // --- State ---
  const config = ref({
    local_cache_path: '',
    global_personal_access_token: '',
    repository_size_threshold_mb: 900,
    image_download_cooldown_seconds: 0.5,
    file_upload_cooldown_seconds: 1.0,
    overwrite_remote_files: false,
    github_repos: [],
  });

  const stats = ref({
    total_images: 0,
    total_size_bytes: 0,
    repo_count: 0,
    total_capacity_bytes: 0,
    type_counts: { poster: 0, logo: 0, fanart: 0 },
    repo_details: [],
  });

  const isLoading = ref(false);
  const isSaving = ref(false);
  const isStatsLoading = ref(false);

  // --- Getters ---
  const totalSpaceUsedPercent = computed(() => {
    if (!stats.value.total_capacity_bytes) return 0;
    return Math.round((stats.value.total_size_bytes / stats.value.total_capacity_bytes) * 100);
  });

  const totalSpaceUsedText = computed(() => {
    const used = stats.value.total_size_bytes;
    const total = stats.value.total_capacity_bytes;
    return `${formatBytes(used)} / ${formatBytes(total)}`;
  });

  // --- Actions ---
  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 });
  };

  const formatBytes = (bytes, decimals = 2) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  };

  async function fetchConfig() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/config`);
      if (!response.ok) throw new Error('获取配置失败');
      const data = await response.json();
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
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '保存配置失败');
      showMessage('success', data.message);
      await fetchConfig(); // 保存后重新获取最新配置
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  async function fetchStats() {
    isStatsLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/stats`);
      if (!response.ok) throw new Error('获取状态概览失败');
      stats.value = await response.json();
    } catch (error) {
      showMessage('error', error.message);
    } finally {
      isStatsLoading.value = false;
    }
  }

  async function startBackup(scope, contentTypes, overwrite) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/start-backup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, content_types: contentTypes, overwrite }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动备份任务失败');
      showMessage('success', data.message);
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  async function startRestore(scope, contentTypes) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/start-restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, content_types: contentTypes }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动恢复任务失败');
      showMessage('success', data.message);
    } catch (error) {
      showMessage('error', error.message);
    }
  }

  // frontend/src/stores/posterManager.js (函数替换)

  async function fetchSingleItemDetails(itemId) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/item-details/${itemId}`);
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || '获取单项详情失败');
      }
      
      const details = await response.json();

      // --- 新增：处理 Emby 图片 URL ---
      // 确保后端返回的相对路径在前端能被正确请求
      if (details && details.emby) {
        for (const imageType in details.emby) {
          const imageInfo = details.emby[imageType];
          if (imageInfo && imageInfo.url && imageInfo.url.startsWith('/api/')) {
            imageInfo.url = `${API_BASE_URL}${imageInfo.url}`;
          }
        }
      }
      // --- 新增结束 ---

      return details;
    } catch (error) {
      showMessage('error', error.message);
      return null;
    }
  }

  async function backupSingleImage(itemId, imageType) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/backup-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, image_type: imageType }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '备份失败');
      showMessage('success', data.message);
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    }
  }

  async function deleteSingleImage(itemId, imageType) {
    try {
      await ElMessageBox.confirm(
        `确定要从 GitHub 备份中永久删除此 ${imageType} 吗？此操作不可恢复。`,
        '警告',
        {
          confirmButtonText: '确定删除',
          cancelButtonText: '取消',
          type: 'warning',
        }
      );
      const response = await fetch(`${API_BASE_URL}/api/poster-manager/delete-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, image_type: imageType }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '删除失败');
      showMessage('success', data.message);
      return true;
    } catch (error) {
      if (error !== 'cancel') {
        showMessage('error', error.message);
      }
      return false;
    }
  }

  return {
    config,
    stats,
    isLoading,
    isSaving,
    isStatsLoading,
    totalSpaceUsedPercent,
    totalSpaceUsedText,
    formatBytes,
    fetchConfig,
    saveConfig,
    fetchStats,
    startBackup,
    startRestore,
    fetchSingleItemDetails,
    backupSingleImage,
    deleteSingleImage,
  };
});