// frontend/src/stores/episodeRoleSync.js (新文件)

import { defineStore } from 'pinia';
import { API_BASE_URL } from '@/config/apiConfig';

export const useEpisodeRoleSyncStore = defineStore('episodeRoleSync', () => {
  
  async function saveConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/episode-role-sync/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  return {
    saveConfig,
  };
});