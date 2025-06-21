// frontend/src/views/ServerConfigView.vue (修改后)
<template>
  <div class="config-page">
    <template v-if="configStore.isLoaded">
      <div class="page-header">
        <h2>Emby 配置</h2>
        <p>所有功能都依赖此配置。请确保信息正确并成功连接。</p>
      </div>

      <!-- 数据源配置区 -->
      <el-form
        ref="serverFormRef"
        :model="localServerConfig"
        :rules="serverFormRules"
        class="config-section"
        label-position="left"
        :label-width="formLabelWidth"
        @submit.prevent="handleSaveServer(serverFormRef)"
        hide-required-asterisk
      >
        <h3>数据源</h3>
        <el-form-item label="Emby 服务器 URL" prop="server">
          <el-input v-model="localServerConfig.server" class="glow-input" placeholder="例如: http://192.168.1.100:8096" />
        </el-form-item>
        <el-form-item label="Emby API Key" prop="api_key">
          <el-input v-model="localServerConfig.api_key" class="glow-input" placeholder="从 Emby 控制台获取" show-password />
        </el-form-item>
        <el-form-item label="Emby 用户 ID" prop="user_id">
          <el-input v-model="localServerConfig.user_id" class="glow-input" placeholder="从 Emby 控制台获取" />
        </el-form-item>
        <el-form-item class="form-button-container">
          <el-button type="success" native-type="submit" :loading="isServerLoading">
            保存并测试连接
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 网络设置配置区 -->
      <el-form
        ref="proxyFormRef"
        :model="localProxyConfig"
        :rules="proxyFormRules"
        class="config-section"
        label-position="left"
        :label-width="formLabelWidth"
        @submit.prevent="handleSaveProxy(proxyFormRef)"
        hide-required-asterisk
      >
        <h3>网络设置</h3>
        <el-form-item label="启用代理">
          <el-switch v-model="localProxyConfig.enabled" />
          <div class="form-item-description">
            全局开关，用于启用或禁用下方的代理配置。
          </div>
        </el-form-item>
        <el-form-item label="HTTP 代理地址" prop="url">
          <el-input 
            v-model="localProxyConfig.url" 
            class="glow-input" 
            placeholder="例如: http://127.0.0.1:7890" 
            :disabled="!localProxyConfig.enabled"
          />
        </el-form-item>
        <el-form-item label="代理模式">
          <el-radio-group v-model="localProxyConfig.mode" :disabled="!localProxyConfig.enabled">
            <el-radio value="blacklist">黑名单模式 (推荐)</el-radio>
            <el-radio value="whitelist">白名单模式</el-radio>
          </el-radio-group>
          <div class="form-item-description">
            <b>黑名单模式：</b>默认所有外部请求都走代理，可勾选下方目标<b>不走</b>代理。<br>
            <b>白名单模式：</b>默认所有外部请求都不走代理，需勾选下方目标<b>走</b>代理。
          </div>
        </el-form-item>
        <el-form-item label="代理目标">
          <div class="proxy-scope-group">
            <el-checkbox v-model="localProxyConfig.target_tmdb" :disabled="!localProxyConfig.enabled">TMDB</el-checkbox>
            <el-checkbox v-model="localProxyConfig.target_douban" :disabled="!localProxyConfig.enabled">豆瓣 (及图片)</el-checkbox>
            <el-checkbox v-model="localProxyConfig.target_emby" :disabled="!localProxyConfig.enabled">Emby 服务器</el-checkbox>
          </div>
           <div class="form-item-description">
            {{ proxyTargetDescription }}
          </div>
        </el-form-item>
        <el-form-item label="高级: 排除列表">
          <el-input 
            v-model="localProxyConfig.exclude" 
            type="textarea"
            :rows="2"
            class="glow-input" 
            placeholder="例如: example.com,*.another-domain.com"
            :disabled="!localProxyConfig.enabled"
          />
          <div class="form-item-description">
            作为补充手段，指定哪些域名不走代理，多个地址用英文逗号(,)隔开。此功能依赖于后端环境支持。
          </div>
        </el-form-item>
        <el-form-item class="form-button-container multi-button">
          <el-button @click="handleTestProxy" :loading="isProxyTesting" :disabled="!localProxyConfig.enabled">
            测试代理
          </el-button>
          <el-button type="success" native-type="submit" :loading="isProxySaving">
            保存代理设置
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 下载设置配置区 -->
      <el-form
        ref="downloadFormRef"
        :model="localDownloadConfig"
        :rules="downloadFormRules"
        class="config-section"
        label-position="left"
        :label-width="formLabelWidth"
        @submit.prevent="handleSaveDownload(downloadFormRef)"
        hide-required-asterisk
      >
        <h3>下载设置</h3>
        <el-form-item label="全局下载目录" prop="download_directory">
          <el-input v-model="localDownloadConfig.download_directory" class="glow-input" placeholder="D:\emby_downloads" />
          <div class="form-item-description">
            所有从本工具下载的媒体文件（如NFO、图片）都将保存在此目录下。
          </div>
        </el-form-item>
        <el-form-item label="同名文件处理">
          <div>
            <el-radio-group v-model="localDownloadConfig.download_behavior">
              <el-radio value="skip">跳过下载</el-radio>
              <el-radio value="overwrite">覆盖源文件</el-radio>
            </el-radio-group>
            <div class="form-item-description">
              当下载目标位置已存在同名文件时的处理策略。
            </div>
          </div>
        </el-form-item>
        <el-form-item label="目录命名规则">
          <div>
            <el-radio-group v-model="localDownloadConfig.directory_naming_rule">
              <el-radio value="tmdb_id">按TMDB ID命名</el-radio>
              <el-radio value="media_path">按媒体路径命名</el-radio>
            </el-radio-group>
            <div class="form-item-description">
              选择在全局下载目录下创建子目录的命名方式。
            </div>
          </div>
        </el-form-item>
        <el-form-item label="NFO演员数量">
          <div>
            <el-input-number v-model="localDownloadConfig.nfo_actor_limit" :min="0" :max="200" />
            <div class="form-item-description">
              写入 NFO 文件中的最大演员数量。设为 0 则不写入任何演员信息。
            </div>
          </div>
        </el-form-item>
        <el-form-item class="form-button-container">
          <el-button type="success" native-type="submit" :loading="isDownloadLoading">
            保存下载设置
          </el-button>
        </el-form-item>
      </el-form>

      <!-- TMDB 配置区 -->
      <el-form
        ref="tmdbFormRef"
        :model="localTmdbConfig"
        :rules="tmdbFormRules"
        class="config-section"
        label-position="left"
        :label-width="formLabelWidth"
        @submit.prevent="handleSaveAndTestTmdb(tmdbFormRef)"
        hide-required-asterisk
      >
        <h3>TMDB 数据源</h3>
        <el-form-item label="TMDB API Key" prop="api_key">
          <el-input v-model="localTmdbConfig.api_key" class="glow-input" placeholder="从 The Movie Database 官网申请" show-password />
          <div class="form-item-description">
            用于从 TMDB 获取更丰富的元数据，例如演员头像、影视海报等。
          </div>
        </el-form-item>
        <el-form-item label="自定义API域名">
          <el-switch v-model="localTmdbConfig.custom_api_domain_enabled" />
           <div class="form-item-description">
            在无法访问默认 `api.themoviedb.org` 时，可启用此项并指定一个可用的反代域名。
          </div>
        </el-form-item>
        <el-form-item label="API 域名地址">
          <el-input 
            v-model="localTmdbConfig.custom_api_domain" 
            class="glow-input" 
            placeholder="例如: https://api.tmdb.org"
            :disabled="!localTmdbConfig.custom_api_domain_enabled"
          />
        </el-form-item>
        <el-form-item class="form-button-container">
          <el-button type="success" native-type="submit" :loading="isTmdbLoading">
            保存并测试
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 豆瓣数据源配置区 -->
      <el-form
        ref="doubanFormRef"
        :model="localDoubanConfig"
        class="config-section"
        label-position="left"
        :label-width="formLabelWidth"
        @submit.prevent="handleSaveDouban(doubanFormRef)"
        hide-required-asterisk
      >
        <h3>豆瓣数据源设置</h3>

        <div class="cache-status-bar">
          <span v-if="!configStore.appConfig.douban_cache_status?.exists">
            缓存状态: 缓存文件不存在，请配置目录后强制刷新
          </span>
          <span v-else>
            缓存状态: {{ configStore.appConfig.douban_cache_status.is_scanning ? '扫描中...' : '空闲' }} | 
            数据量: {{ configStore.appConfig.douban_cache_status.item_count }} 条 | 
            最后更新: {{ configStore.appConfig.douban_cache_status.last_modified ? new Date(configStore.appConfig.douban_cache_status.last_modified).toLocaleString() : 'N/A' }}
          </span>
        </div>

        <el-form-item label="豆瓣数据根目录">
          <el-input v-model="localDoubanConfig.directory" class="glow-input" placeholder="包含 'douban-movies' 和 'douban-tv' 的目录" />
          <div class="form-item-description">
            程序启动时若本地无缓存，将自动扫描此目录。此目录的修改将在下次刷新或重启后生效。
          </div>
        </el-form-item>
        <el-form-item label="定时刷新(CRON)">
          <el-input v-model="localDoubanConfig.refresh_cron" class="glow-input" placeholder="例如: 0 3 * * 1 (每周一凌晨3点)" />
          <div class="form-item-description">
            使用标准的CRON表达式来定时刷新本地豆瓣数据。留空则禁用定时刷新。
          </div>
        </el-form-item>
        
        <el-form-item label="额外保存字段">
          <!-- --- 核心修改 4: 移除“国家/地区”的复选框 --- -->
          <el-checkbox-group v-model="localDoubanConfig.extra_fields" class="extra-fields-group">
            <el-checkbox value="rating">评分</el-checkbox>
            <el-checkbox value="pubdate">上映日期</el-checkbox>
            <el-checkbox value="card_subtitle">卡片副标题</el-checkbox>
            <el-checkbox value="languages">语言</el-checkbox>
            <el-checkbox value="durations">片长(仅电影)</el-checkbox>
          </el-checkbox-group>
          <div class="form-item-description">
            选择要在本地缓存中额外保存的字段，可以减少文件大小。“国家/地区”字段为功能必需，将默认保存。
          </div>
        </el-form-item>

        <el-form-item class="form-button-container multi-button">
          <el-button type="success" native-type="submit" :loading="isDoubanLoading">
            保存豆瓣设置
          </el-button>
          <el-button type="primary" @click="handleForceRefresh" :loading="doubanStore.isLoading">
            强制刷新本地数据
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 豆瓣ID修复器配置区 -->
      <el-form
        ref="doubanFixerFormRef"
        :model="localDoubanFixerConfig"
        class="config-section"
        label-position="left"
        :label-width="formLabelWidth"
        @submit.prevent="handleSaveDoubanFixer(doubanFixerFormRef)"
        hide-required-asterisk
      >
        <h3>豆瓣ID修复器设置</h3>
        <el-form-item label="豆瓣 Cookie">
          <el-input 
            v-model="localDoubanFixerConfig.cookie" 
            type="textarea"
            :rows="3"
            class="glow-input" 
            placeholder="从浏览器开发者工具中获取"
          />
          <div class="form-item-description">
            用于模拟登录状态请求豆瓣，提高搜索成功率。请确保Cookie的有效性。
          </div>
        </el-form-item>
        <el-form-item label="API 冷却时间">
          <el-input-number v-model="localDoubanFixerConfig.api_cooldown" :precision="1" :step="0.5" :min="0.5" />
          <span style="margin-left: 10px;">秒</span>
          <div class="form-item-description">
            每次请求豆瓣API之间的间隔时间，用于防止因请求过快被封禁。推荐 2-5 秒。
          </div>
        </el-form-item>
        <el-form-item label="定时扫描(CRON)">
          <el-input v-model="localDoubanFixerConfig.scan_cron" class="glow-input" placeholder="例如: 0 4 * * * (每天凌晨4点)" />
          <div class="form-item-description">
            使用CRON表达式定时执行全量扫描和自动匹配任务。留空则禁用。
          </div>
        </el-form-item>
        <el-form-item class="form-button-container multi-button">
          <el-button @click="handleTestCookie" :loading="isCookieTesting">
            测试 Cookie
          </el-button>
          <el-button type="success" native-type="submit" :loading="isDoubanFixerLoading">
            保存修复器设置
          </el-button>
        </el-form-item>
      </el-form>

    </template>

    <template v-else>
      <div class="page-header">
        <el-skeleton :rows="1" animated />
      </div>
      <div class="config-section">
        <el-skeleton-item variant="h3" style="width: 120px; margin-bottom: 20px;" />
        <el-skeleton :rows="3" animated />
      </div>
      <div class="config-section">
        <el-skeleton-item variant="h3" style="width: 120px; margin-bottom: 20px;" />
        <el-skeleton :rows="2" animated />
      </div>
      <div class="config-section">
        <el-skeleton-item variant="h3" style="width: 120px; margin-bottom: 20px;" />
        <el-skeleton :rows="1" animated />
      </div>
    </template>
  </div>
</template>

<script setup>
// <script> 部分无需修改，保持原样即可
import { ref, onMounted, watch, computed, reactive } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useDoubanStore } from '@/stores/douban'
import { useTaskStore } from '@/stores/task'
import { ElMessage } from 'element-plus'
import { useWindowSize } from '@vueuse/core'
import { API_BASE_URL } from '@/config/apiConfig';

const configStore = useConfigStore()
const doubanStore = useDoubanStore()
const taskStore = useTaskStore()

const serverFormRef = ref(null)
const downloadFormRef = ref(null)
const doubanFormRef = ref(null)
const tmdbFormRef = ref(null)
const proxyFormRef = ref(null)
const doubanFixerFormRef = ref(null)

const localServerConfig = ref({ server: '', api_key: '', user_id: '' })
const localDownloadConfig = ref({ download_directory: '', download_behavior: 'skip', directory_naming_rule: 'tmdb_id' , nfo_actor_limit: 20 })
const localDoubanConfig = ref({ directory: '', refresh_cron: '', extra_fields: [] })
const localTmdbConfig = ref({ api_key: '', custom_api_domain_enabled: false, custom_api_domain: '' })
const localProxyConfig = ref({ 
  enabled: false, 
  url: '', 
  exclude: '', 
  mode: 'blacklist',
  target_tmdb: false,
  target_douban: true,
  target_emby: true,
})
const localDoubanFixerConfig = ref({ cookie: '', api_cooldown: 2.0, scan_cron: '' })

const isServerLoading = ref(false)
const isDownloadLoading = ref(false)
const isDoubanLoading = ref(false)
const isTmdbLoading = ref(false)
const isProxySaving = ref(false)
const isProxyTesting = ref(false)
const isDoubanFixerLoading = ref(false)
const isCookieTesting = ref(false)

const proxyTargetDescription = computed(() => {
  if (localProxyConfig.value.mode === 'blacklist') {
    return '当前为黑名单模式，请勾选不走代理的目标。常见设置为：勾选豆瓣和Emby，不勾选TMDB。';
  } else {
    return '当前为白名单模式，请勾选需要走代理的目标。常见设置为：仅勾选TMDB。';
  }
});

const serverFormRules = reactive({
  server: [{ required: true, message: '服务器地址不能为空' }],
  api_key: [{ required: true, message: 'API Key 不能为空' }],
  user_id: [{ required: true, message: '用户 ID 不能为空' }],
})

const downloadFormRules = reactive({
  download_directory: [{ required: true, message: '下载目录不能为空' }],
})

const tmdbFormRules = reactive({
  api_key: [{ required: true, message: 'TMDB API Key 不能为空' }],
  custom_api_domain: [{
    validator: (rule, value, callback) => {
      if (localTmdbConfig.value.custom_api_domain_enabled && !value) {
        callback(new Error('启用自定义域名后，地址不能为空'))
      } else if (value && !value.startsWith('http://') && !value.startsWith('https://')) {
        callback(new Error('域名地址必须以 http:// 或 https:// 开头'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }]
})

const proxyFormRules = reactive({
  url: [{
    validator: (rule, value, callback) => {
      if (localProxyConfig.value.enabled && !value) {
        callback(new Error('启用代理后，代理地址不能为空'))
      } else if (value && !value.startsWith('http://') && !value.startsWith('https://')) {
        callback(new Error('代理地址必须以 http:// 或 https:// 开头'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }]
})

const { width } = useWindowSize()
const formLabelWidth = computed(() => (width.value < 768 ? '100%' : '150px'))

onMounted(() => {
  taskStore.connect()
})

watch(() => configStore.appConfig, (newConfig) => {
  if (newConfig) {
    localServerConfig.value = { ...newConfig.server_config }
    localDownloadConfig.value = { ...newConfig.download_config }
    localDoubanConfig.value = { ...newConfig.douban_config, extra_fields: newConfig.douban_config.extra_fields || [] }
    localTmdbConfig.value = { ...newConfig.tmdb_config }
    localProxyConfig.value = {
      enabled: false, 
      url: '', 
      exclude: '', 
      mode: 'blacklist',
      target_tmdb: false,
      target_douban: true,
      target_emby: true,
      ...newConfig.proxy_config 
    }
    localDoubanFixerConfig.value = {
      cookie: '',
      api_cooldown: 2.0,
      scan_cron: '',
      ...newConfig.douban_fixer_config
    }
  }
}, { deep: true, immediate: true })

watch(() => taskStore.tasks, (newTasks, oldTasks) => {
  oldTasks.forEach(oldTask => {
    if (oldTask.name.includes('豆瓣') && !newTasks.some(t => t.id === oldTask.id)) {
      setTimeout(() => {
        configStore.isLoaded = false; 
        configStore.fetchConfig();
      }, 500);
    }
  });
}, { deep: true });

const showMessage = (type, message) => {
  ElMessage({
    message: message,
    type: type,
    showClose: true,
    duration: 3000,
    customClass: `custom-message custom-message-${type}`,
    offset: 20,
  })
}

const handleSaveServer = async (formEl) => {
  if (!formEl) return
  await formEl.validate(async (valid) => {
    if (valid) {
      isServerLoading.value = true
      const result = await configStore.saveAndTestServerConfig(localServerConfig.value)
      
      if (result.success) {
        let successMessage = result.message; 
        if (result.details) {
          const { serverName, serverVersion, userName } = result.details;
          successMessage = `Emby配置已保存！连接成功！Emby 服务器: ${serverName}, 版本: ${serverVersion}。欢迎，${userName}。`;
        }
        showMessage('success', successMessage);
      } else {
        showMessage('error', result.message);
      }

      isServerLoading.value = false
    } else {
      showMessage('warning', '请填写所有必填项！')
      return false
    }
  })
}

const handleSaveDownload = async (formEl) => {
  if (!formEl) return
  await formEl.validate(async (valid) => {
    if (valid) {
      isDownloadLoading.value = true
      const result = await configStore.saveDownloadConfig(localDownloadConfig.value)
      showMessage(result.success ? 'success' : 'error', result.message)
      isDownloadLoading.value = false
    } else {
      showMessage('warning', '请填写下载目录！')
      return false
    }
  })
}

const handleSaveProxy = async (formEl) => {
  if (!formEl) return
  await formEl.validate(async (valid) => {
    if (valid) {
      isProxySaving.value = true
      const result = await configStore.saveProxyConfig(localProxyConfig.value)
      showMessage(result.success ? 'success' : 'error', result.message)
      isProxySaving.value = false
    } else {
      showMessage('warning', '请检查代理地址格式！')
      return false
    }
  })
}

const handleTestProxy = async () => {
  await proxyFormRef.value.validate(async (valid) => {
    if (valid) {
      if (localProxyConfig.value.enabled && !localProxyConfig.value.url) {
        showMessage('warning', '请先填写代理地址再进行测试！');
        return;
      }
      isProxyTesting.value = true;
      try {
        const response = await fetch(`${API_BASE_URL}/api/config/proxy/test`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(localProxyConfig.value),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || '测试请求失败');
        }
        let successMessage = data.message;
        if (data.latency) {
          successMessage += ` 延迟: ${data.latency}`;
        }
        showMessage('success', successMessage);
      } catch (error) {
        showMessage('error', `代理测试失败: ${error.message}`);
      } finally {
        isProxyTesting.value = false;
      }
    } else {
      showMessage('warning', '请修正代理地址格式后再测试！');
    }
  });
};

const handleSaveAndTestTmdb = async (formEl) => {
  if (!formEl) return
  await formEl.validate(async (valid) => {
    if (valid) {
      isTmdbLoading.value = true
      const result = await configStore.saveAndTestTmdbConfig(localTmdbConfig.value)
      showMessage(result.success ? 'success' : 'error', result.message)
      isTmdbLoading.value = false
    } else {
      showMessage('warning', '请填写必填项并检查格式！')
      return false
    }
  })
}

const handleSaveDouban = async (formEl) => {
  if (!formEl) return
  await formEl.validate(async (valid) => {
    if (valid) {
      isDoubanLoading.value = true
      const result = await configStore.saveDoubanConfig(localDoubanConfig.value)
      showMessage(result.success ? 'success' : 'error', result.message)
      isDoubanLoading.value = false
    } else {
      return false
    }
  })
}

const handleSaveDoubanFixer = async (formEl) => {
  if (!formEl) return;
  await formEl.validate(async (valid) => {
    if (valid) {
      isDoubanFixerLoading.value = true;
      const result = await configStore.saveDoubanFixerConfig(localDoubanFixerConfig.value);
      showMessage(result.success ? 'success' : 'error', result.message);
      isDoubanFixerLoading.value = false;
    } else {
      return false;
    }
  });
};

const handleTestCookie = async () => {
  if (!localDoubanFixerConfig.value.cookie) {
    showMessage('warning', '请先填写豆瓣 Cookie！');
    return;
  }
  isCookieTesting.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/douban-fixer/test-cookie`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie: localDoubanFixerConfig.value.cookie }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || '测试请求失败');
    }
    showMessage('success', data.message);
  } catch (error) {
    showMessage('error', `Cookie 测试失败: ${error.message}`);
  } finally {
    isCookieTesting.value = false;
  }
};

const handleForceRefresh = async () => {
  await doubanStore.forceRefresh()
}
</script>

<style>
/* 样式部分无需修改，保持原样即可 */
.el-message-container {
  z-index: 9999 !important;
}
.el-message.custom-message {
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  padding: 12px 16px;
  overflow: hidden;
}
.el-message.custom-message::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: 0;
  height: 4px;
  width: 100%;
  background-color: rgba(0, 0, 0, 0.1);
  animation: progress-bar 3s linear forwards;
}
@keyframes progress-bar {
  from { width: 100%; }
  to { width: 0%; }
}
.el-message.custom-message-success {
  background-color: #f0f9eb !important;
  color: #67c23a !important;
  border: 1px solid #e1f3d8 !important;
}
.el-message.custom-message-success .el-message__content {
  color: #67c23a !important;
}
.el-message.custom-message-success::after {
  background-color: #b3e19d;
}
.el-message.custom-message-warning {
  background-color: #fdf6ec !important;
  color: #e6a23c !important;
  border: 1px solid #faecd8 !important;
}
.el-message.custom-message-warning .el-message__content {
  color: #e6a23c !important;
}
.el-message.custom-message-warning::after {
  background-color: #f3d19e;
}
.el-message.custom-message-error {
  background-color: #fef0f0 !important;
  color: #f56c6c !important;
  border: 1px solid #fde2e2 !important;
}
.el-message.custom-message-error .el-message__content {
  color: #f56c6c !important;
}
.el-message.custom-message-error::after {
  background-color: #fab6b6;
}
</style>

<style scoped>
.config-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
}

.config-page :deep(.el-radio__input.is-checked .el-radio__inner),
.config-page :deep(.el-checkbox__input.is-checked .el-checkbox__inner),
.config-page :deep(.el-switch.is-checked .el-switch__core) {
  border-color: var(--custom-theme-color);
  background: var(--custom-theme-color);
}
.config-page :deep(.el-radio__input.is-checked+.el-radio__label),
.config-page :deep(.el-checkbox__input.is-checked+.el-checkbox__label) {
  color: var(--custom-theme-color);
}

.config-section :deep(.glow-input .el-input__wrapper),
.config-section :deep(.glow-input .el-textarea__inner) {
  background-color: var(--el-fill-color-light);
  box-shadow: none;
  border-radius: 8px;
  border: 1px solid transparent; 
  transition: all 0.3s ease;
}
.config-section :deep(.glow-input .el-input__wrapper:hover),
.config-section :deep(.glow-input .el-textarea__inner:hover) { 
  border-color: var(--custom-theme-color); 
}
.config-section :deep(.glow-input.is-focus .el-input__wrapper),
.config-section :deep(.glow-input .el-textarea__inner:focus) {
  border-color: var(--custom-theme-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--custom-theme-color) 30%, transparent), 0 0 8px color-mix(in srgb, var(--custom-theme-color) 20%, transparent);
}

.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  margin-bottom: 20px;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }
.config-section { margin-bottom: 40px; }
.config-section h3 {
  font-size: 1.1rem;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.el-form-item { max-width: 800px; }
.form-button-container { margin-left: 0 !important; }
.form-button-container :deep(.el-form-item__content) {
  justify-content: center;
  margin-left: 0 !important;
}
.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}
.el-button--success {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
}
.multi-button :deep(.el-form-item__content) {
  display: flex;
  gap: 20px;
}
.extra-fields-group {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
}
@media (max-width: 768px) {
  .config-section :deep(.el-form-item__label) {
    justify-content: flex-start;
  }
}

.cache-status-bar {
  background-color: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  padding: 12px 20px;
  border-radius: 8px;
  margin-bottom: 25px; 
  margin-top: -5px;
  text-align: center;
  font-size: 14px;
  border: 1px solid var(--el-border-color-lighter);
}

.proxy-scope-group {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
}
</style>