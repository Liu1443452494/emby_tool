import { ref } from 'vue'
import { defineStore } from 'pinia'
import { API_BASE_URL } from '@/config/apiConfig';


// === 文件: frontend/src/stores/config.js === #

export const useConfigStore = defineStore('config', () => {
  const isLoaded = ref(false)
  const appConfig = ref({
    server_config: { server: '', api_key: '', user_id: '' },
    download_config: { download_directory: '', download_behavior: 'skip', directory_naming_rule: 'tmdb_id' , nfo_actor_limit: 20},
    tmdb_config: { api_key: '', custom_api_domain_enabled: false, custom_api_domain: '' },
    proxy_config: { enabled: false, url: '', exclude: '', mode: 'blacklist', target_tmdb: false, target_douban: true, target_emby: true, custom_rules: [] },
    douban_config: { directory: '', refresh_cron: '', extra_fields: [] },
    actor_localizer_config: {
      replace_english_role: false,
      enhance_english_role_with_douban: true,
      translation_enabled: false,
      translation_mode: "translators",
      translator_engine: "baidu",
      api_cooldown_enabled: true,
      api_cooldown_time: 0.2,
      person_limit: 15,
      tencent_config: { secret_id: '', secret_key: '', region: 'ap-guangzhou' },
      siliconflow_config: { api_key: '', model_name: 'Qwen/Qwen2-7B-Instruct', model_remarks: {} }
    },
    douban_fixer_config: { cookie: '', api_cooldown: 2.0, scan_cron: '' },
    scheduled_tasks_config: {
      target_scope: {
        mode: 'latest',
        days: 7,
        limit: 100,
        media_type: 'Movie',
        library_ids: [],
        library_blacklist: '',
        item_ids: []
      },
      tasks: []
    },
    douban_poster_updater_config: {
      update_interval: 1.0,
      overwrite_existing: false,
      skip_mainland_china: false
    },
    webhook_config: {
      enabled: false,
      initial_wait_time: 30,
      plugin_wait_time: 60
    },
    episode_refresher_config: {
      refresh_mode: 'emby',
      overwrite_metadata: true,
      skip_if_complete: true,
      screenshot_enabled: false,
      screenshot_cache_mode: 'local',
      screenshot_percentage: 10,
      screenshot_fallback_seconds: 150,
      crop_widescreen_to_16_9: true,
      force_overwrite_screenshots: false,
      screenshot_cooldown: 2.0,
      use_smart_screenshot: true,
      backup_overwrite_local: false,
      github_config: {
        repo_url: '',
        branch: 'main',
        personal_access_token: '',
        allow_fallback: true,
        overwrite_remote: false,
        download_cooldown: 0.5,
        upload_cooldown: 1.0,
        delete_cooldown: 1.5,
      }
    },
    episode_renamer_config: {
      emby_path_root: '/media',
      clouddrive_path_root: '/cd2',
      clouddrive_rename_cooldown: 1.0
    },
    telegram_config: {
      enabled: false,
      bot_token: '',
      chat_id: ''
    }
  })
  const isConnected = ref(false)


  async function fetchConfig() {
    if (isLoaded.value) {
      return
    }
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/config`)
      if (response.ok) {
        const fullConfig = await response.json()
        if (!fullConfig.proxy_config) {
          fullConfig.proxy_config = { enabled: false, url: '', exclude: '', mode: 'blacklist', target_tmdb: false, target_douban: true, target_emby: true, custom_rules: [] };
        } else if (!fullConfig.proxy_config.custom_rules) {
          fullConfig.proxy_config.custom_rules = [];
        }
        if (!fullConfig.tmdb_config) {
          fullConfig.tmdb_config = { api_key: '', custom_api_domain_enabled: false, custom_api_domain: '' };
        }
        if (!fullConfig.download_config) {
          fullConfig.download_config = { download_directory: '', download_behavior: 'skip', directory_naming_rule: 'tmdb_id' };
        }
        if (typeof fullConfig.download_config.nfo_actor_limit === 'undefined') {
          fullConfig.download_config.nfo_actor_limit = 20;
        }
        if (!fullConfig.douban_fixer_config) {
          fullConfig.douban_fixer_config = { cookie: '', api_cooldown: 2.0, scan_cron: '' };
        }
        if (!fullConfig.scheduled_tasks_config) {
          fullConfig.scheduled_tasks_config = {
            target_scope: { mode: 'latest', days: 7, limit: 100, media_type: 'Movie', library_ids: [], library_blacklist: '', item_ids: [] },
            tasks: []
          };
        } else if (!fullConfig.scheduled_tasks_config.target_scope) {
           fullConfig.scheduled_tasks_config.target_scope = { mode: 'latest', days: 7, limit: 100, media_type: 'Movie', library_ids: [], library_blacklist: '', item_ids: [] };
        }
        if (typeof fullConfig.scheduled_tasks_config.target_scope.item_ids === 'undefined') {
          fullConfig.scheduled_tasks_config.target_scope.item_ids = [];
        }
        
        if (!fullConfig.douban_poster_updater_config) {
          fullConfig.douban_poster_updater_config = { update_interval: 1.0, overwrite_existing: false, skip_mainland_china: false };
        } else if (typeof fullConfig.douban_poster_updater_config.skip_mainland_china === 'undefined') {
          fullConfig.douban_poster_updater_config.skip_mainland_china = false;
        }

        if (!fullConfig.webhook_config) {
          fullConfig.webhook_config = { enabled: false, initial_wait_time: 30, plugin_wait_time: 60 };
        }
        
        if (!fullConfig.episode_refresher_config) {
          fullConfig.episode_refresher_config = { 
            refresh_mode: 'emby', 
            overwrite_metadata: true, 
            skip_if_complete: true,
            screenshot_enabled: false,
            screenshot_cache_mode: 'local',
            screenshot_percentage: 10,
            screenshot_fallback_seconds: 150,
            crop_widescreen_to_16_9: true,
            force_overwrite_screenshots: false,
            screenshot_cooldown: 2.0,
            use_smart_screenshot: true,
            backup_overwrite_local: false,
            github_config: {
              repo_url: '',
              branch: 'main',
              personal_access_token: '',
              allow_fallback: true,
              overwrite_remote: false,
              download_cooldown: 0.5,
              upload_cooldown: 1.0,
            }
          };
        } else {
          const defaultConfig = appConfig.value.episode_refresher_config;
          for (const key in defaultConfig) {
            if (typeof fullConfig.episode_refresher_config[key] === 'undefined') {
              fullConfig.episode_refresher_config[key] = defaultConfig[key];
            }
          }
          if (typeof fullConfig.episode_refresher_config.github_config === 'undefined') {
            fullConfig.episode_refresher_config.github_config = defaultConfig.github_config;
          } else {
            for (const key in defaultConfig.github_config) {
              if (typeof fullConfig.episode_refresher_config.github_config[key] === 'undefined') {
                fullConfig.episode_refresher_config.github_config[key] = defaultConfig.github_config[key];
              }
            }
          }
        }

        if (!fullConfig.episode_renamer_config) {
          fullConfig.episode_renamer_config = { 
            emby_path_root: '/media',
            clouddrive_path_root: '/cd2',
            clouddrive_rename_cooldown: 1.0
          };
        }

        if (!fullConfig.telegram_config) {
          fullConfig.telegram_config = { enabled: false, bot_token: '', chat_id: '' };
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

  async function saveScheduledTasksConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/scheduled-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.scheduled_tasks_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  async function triggerScheduledTaskOnce(taskId) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/scheduled-tasks/${taskId}/trigger`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '触发任务失败');
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  async function saveDoubanPosterUpdaterConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/douban-poster-updater`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.douban_poster_updater_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  async function saveWebhookConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/webhook`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.webhook_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }
  
  async function saveEpisodeRefresherConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/episode-refresher`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.episode_refresher_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }
  
  async function saveEpisodeRenamerConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/episode-renamer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.episode_renamer_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

   async function saveTelegramConfig(newConfig) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/config/telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '未知错误');
      
      appConfig.value.telegram_config = newConfig;
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  async function testTelegramConfig(configToTest) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/notification/test-telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configToTest),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '测试请求失败');
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
    saveDoubanFixerConfig,
    saveScheduledTasksConfig,
    triggerScheduledTaskOnce,
    saveDoubanPosterUpdaterConfig,
    saveWebhookConfig,
    saveEpisodeRefresherConfig,
    saveEpisodeRenamerConfig,
    saveTelegramConfig,
    testTelegramConfig
  }
})