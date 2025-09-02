// frontend/src/stores/mediaTagger.js (完整文件覆盖)

import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { API_BASE_URL } from '@/config/apiConfig'
import _ from 'lodash'

export const useMediaTaggerStore = defineStore('mediaTagger', () => {
  const config = ref({
    enabled: false,
    cron: '0 2 * * *',
    rules: []
  })
  const isLoading = ref(false)

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  async function fetchConfig() {
    try {
      isLoading.value = true
      const response = await fetch(`${API_BASE_URL}/api/media-tagger/config`)
      if (!response.ok) throw new Error('获取配置失败')
      const data = await response.json()
      data.rules = data.rules.map(rule => _.defaultsDeep(rule, {
        target: {
          libraries: { mode: 'all', names: [] },
          genres: { mode: 'any', names: [], match: 'or' }
        },
        action: { add_tags: [], remove_tags: [] }
      }))
      config.value = data
    } catch (error) {
      showMessage('error', error.message)
    } finally {
      isLoading.value = false
    }
  }

  async function saveConfig(newConfig) {
    try {
      isLoading.value = true
      const response = await fetch(`${API_BASE_URL}/api/media-tagger/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '保存失败')
      showMessage('success', data.message)
      await fetchConfig()
      return true
    } catch (error) {
      showMessage('error', error.message)
      return false
    } finally {
      isLoading.value = false
    }
  }

  async function runTagger() {
    try {
      const response = await fetch(`${API_BASE_URL}/api/media-tagger/run`, {
        method: 'POST'
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动任务失败')
      showMessage('success', data.message)
      return true
    } catch (error) {
      showMessage('error', error.message)
      return false
    }
  }

  async function clearAllTags(scope) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/media-tagger/clear-all-tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope: scope })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动任务失败');
      showMessage('success', data.message);
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    }
  }

  async function removeSpecificTags(tags, scope) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/media-tagger/remove-specific-tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags: tags, scope: scope })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '启动任务失败');
      showMessage('success', data.message);
      return true;
    } catch (error) {
      showMessage('error', error.message);
      return false;
    }
  }

  return {
    config,
    isLoading,
    fetchConfig,
    saveConfig,
    runTagger,
    clearAllTags,
    removeSpecificTags
  }
})