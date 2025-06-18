// frontend/src/stores/config.js (修改后)
import { ref } from 'vue'
import { defineStore } from 'pinia'
// --- 核心修改 1: 导入 API 配置 ---
import { API_BASE_URL } from '@/config/apiConfig';

export const useConfigStore = defineStore('config', () => {
  const isLoaded = ref(false)
  const appConfig = ref({
    server_config: { server: '', api_key: '', user_id: '' },
    download_config: { download_directory: '', download_behavior: 'skip', directory_naming_rule: 'tmdb_id' },
    tmdb_config: { api_key: '', custom_api_domain_enabled: false, custom_api_domain: '' },
    proxy_config: { enabled: false, url: '', exclude: '' },
    douban_config: { directory: '', refresh_cron: '', extra_fields: [] },
    actor_localizer_config: {
      replace_english_role: false,
      translation_enabled: false,
      translation_mode: "translators",
      translator_engine: "baidu",
      api_cooldown_enabled: true,
      api_cooldown_time: 0.2,
      person_limit: 15,
      tencent_config: { secret_id: '', secret_key: '', region: 'ap-guangzhou' },
      siliconflow_config: { api_key: '', model_name: 'Qwen/Qwen2-7B-Instruct', model_remarks: {} }
    },
    // --- 新增：为 appConfig 添加默认结构 ---
    douban_fixer_config: { cookie: '', api_cooldown: 2.0, scan_cron: '' }
  })
  const isConnected = ref(false)

  async function fetchConfig() {
    // isLoaded.value = false; // 如果需要强制刷新，可以取消注释
    if (isLoaded.value) {
      return
    }
    
    try {
      // --- 核心修改 2: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config`)
      if (response.ok) {
        const fullConfig = await response.json()
        // 为旧配置提供兼容性保障
        if (!fullConfig.proxy_config) {
          fullConfig.proxy_config = { enabled: false, url: '', exclude: '' };
        }
        if (!fullConfig.tmdb_config) {
          fullConfig.tmdb_config = { api_key: '', custom_api_domain_enabled: false, custom_api_domain: '' };
        }
        if (!fullConfig.download_config) {
          fullConfig.download_config = { download_directory: '', download_behavior: 'skip', directory_naming_rule: 'tmdb_id' };
        }
        // --- 新增：为旧配置提供兼容性 ---
        if (!fullConfig.douban_fixer_config) {
          fullConfig.douban_fixer_config = { cookie: '', api_cooldown: 2.0, scan_cron: '' };
        }
        appConfig.value = fullConfig
      } else {
        console.error('获取配置失败，服务器返回状态:', response.status)
      }
    } catch (error) {
      console.error('获取配置失败:', error)
    } finally {
      isLoaded.value = true
    }
  }

  async function saveAndTestServerConfig(newServerConfig) {
    try {
      // --- 核心修改 3: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config/server`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newServerConfig),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '未知错误')
      
      appConfig.value.server_config = newServerConfig
      isConnected.value = true
      return { success: true, ...data }

    } catch (error) {
      isConnected.value = false
      return { success: false, message: error.message }
    }
  }

  async function saveDownloadConfig(newDownloadConfig) {
    try {
      // --- 核心修改 4: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config/download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newDownloadConfig),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '未知错误')

      appConfig.value.download_config = newDownloadConfig
      return { success: true, message: data.message }
    } catch (error) {
      return { success: false, message: error.message }
    }
  }
  
  async function saveAndTestTmdbConfig(newTmdbConfig) {
    try {
      // --- 核心修改 5: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config/tmdb`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newTmdbConfig),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '未知错误')

      appConfig.value.tmdb_config = newTmdbConfig
      return { success: true, message: data.message }
    } catch (error) {
      return { success: false, message: error.message }
    }
  }

  async function saveDoubanConfig(newDoubanConfig) {
    try {
      // --- 核心修改 6: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config/douban`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newDoubanConfig),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '未知错误')

      appConfig.value.douban_config = newDoubanConfig
      return { success: true, message: data.message }
    } catch (error) {
      return { success: false, message: error.message }
    }
  }

  async function saveActorLocalizerConfig(newConfig) {
    try {
      // --- 核心修改 7: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config/actor-localizer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '未知错误')

      appConfig.value.actor_localizer_config = newConfig
      return { success: true, message: data.message }
    } catch (error) {
      return { success: false, message: error.message }
    }
  }

  async function saveProxyConfig(newProxyConfig) {
    try {
      // --- 核心修改 8: 使用导入的常量 ---
      const response = await fetch(`${API_BASE_URL}/api/config/proxy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newProxyConfig),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '未知错误')

      appConfig.value.proxy_config = newProxyConfig
      return { success: true, message: data.message }
    } catch (error) {
      return { success: false, message: error.message }
    }
  }

  // --- 新增：保存豆瓣ID修复器配置的 action ---
  async function saveDoubanFixerConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/douban-fixer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.douban_fixer_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  return { 
    appConfig, 
    isLoaded,
    isConnected, 
    fetchConfig, 
    saveAndTestServerConfig, 
    saveDownloadConfig,
    saveAndTestTmdbConfig,
    saveDoubanConfig,
    saveActorLocalizerConfig,
    saveProxyConfig,
    // --- 新增：导出新方法 ---
    saveDoubanFixerConfig
  }
})