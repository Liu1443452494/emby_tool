<!-- frontend/src/views/ServerConfigView.vue (template 完整覆盖) -->
<template>
  <div class="config-page">
    <template v-if="configStore.isLoaded">
      <div class="page-header">
        <!-- --- 修改 --- -->
        <div class="header-content">
          <h2>配置中心</h2>
          <p>所有功能都依赖此配置。请确保信息正确并成功连接。</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Download" @click="handleExportConfig">导出配置</el-button>
          <el-button :icon="Upload" @click="handleImportConfig">导入配置</el-button>
        </div>
        <!-- --- 修改结束 --- -->
      </div>

      <!-- --- 修改：移除 type="border-card"，并为 el-tab-pane 添加 transition --- -->
      <el-tabs v-model="activeTab" class="config-tabs">
        <!-- Emby 服务器配置 -->
        <el-tab-pane label="Emby 服务器" name="server">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'server'"
              ref="serverFormRef"
              :model="localServerConfig"
              :rules="serverFormRules"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveServer(serverFormRef)"
              hide-required-asterisk
            >
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
          </transition>
        </el-tab-pane>

        <!-- 网络设置 -->
        <el-tab-pane label="网络代理" name="network">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'network'"
              ref="proxyFormRef"
              :model="localProxyConfig"
              :rules="proxyFormRules"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveProxy(proxyFormRef)"
              hide-required-asterisk
            >
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
              <el-form-item label="内置代理目标">
                <div class="proxy-scope-group">
                  <el-checkbox v-model="localProxyConfig.target_tmdb" :disabled="!localProxyConfig.enabled">TMDB</el-checkbox>
                  <el-checkbox v-model="localProxyConfig.target_douban" :disabled="!localProxyConfig.enabled">豆瓣 (及图片)</el-checkbox>
                  <el-checkbox v-model="localProxyConfig.target_emby" :disabled="!localProxyConfig.enabled">Emby 服务器</el-checkbox>
                </div>
                <div class="form-item-description">
                  {{ proxyTargetDescription }}
                </div>
              </el-form-item>
              <el-form-item>
                <el-button @click="openProxyRulesDialog" :disabled="!localProxyConfig.enabled">
                  自定义代理规则...
                </el-button>
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
          </transition>
        </el-tab-pane>

        <!-- 下载设置 -->
        <el-tab-pane label="下载设置" name="download">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'download'"
              ref="downloadFormRef"
              :model="localDownloadConfig"
              :rules="downloadFormRules"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveDownload(downloadFormRef)"
              hide-required-asterisk
            >
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
          </transition>
        </el-tab-pane>

        <!-- TMDB 数据源 -->
        <el-tab-pane label="TMDB" name="tmdb">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'tmdb'"
              ref="tmdbFormRef"
              :model="localTmdbConfig"
              :rules="tmdbFormRules"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveAndTestTmdb(tmdbFormRef)"
              hide-required-asterisk
            >
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
          </transition>
        </el-tab-pane>

        <!-- 豆瓣数据源 -->
        <el-tab-pane label="豆瓣神医数据" name="douban">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'douban'"
              ref="doubanFormRef"
              :model="localDoubanConfig"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveDouban(doubanFormRef)"
              hide-required-asterisk
            >
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
          </transition>
        </el-tab-pane>

        <!-- 豆瓣ID修复器 -->
        <el-tab-pane label="豆瓣COOKIE" name="douban-fixer">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'douban-fixer'"
              ref="doubanFixerFormRef"
              :model="localDoubanFixerConfig"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveDoubanFixer(doubanFixerFormRef)"
              hide-required-asterisk
            >
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
          </transition>
        </el-tab-pane>

        <!-- 通知设置 -->
        <el-tab-pane label="TG通知设置" name="notification">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'notification'"
              ref="telegramFormRef"
              :model="localTelegramConfig"
              :rules="telegramFormRules"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveTelegram(telegramFormRef)"
              hide-required-asterisk
            >
              <el-form-item label="启用Telegram通知">
                <el-switch v-model="localTelegramConfig.enabled" />
                <div class="form-item-description">
                  全局开关，用于启用或禁用所有通过Telegram发送的通知。
                </div>
              </el-form-item>
              <el-form-item label="Bot Token" prop="bot_token">
                <el-input 
                  v-model="localTelegramConfig.bot_token" 
                  class="glow-input" 
                  placeholder="从 @BotFather 获取" 
                  :disabled="!localTelegramConfig.enabled"
                  show-password
                />
              </el-form-item>
              <el-form-item label="Chat ID" prop="chat_id">
                <el-input 
                  v-model="localTelegramConfig.chat_id" 
                  class="glow-input" 
                  placeholder="个人、群组或频道的ID" 
                  :disabled="!localTelegramConfig.enabled"
                />
                <div class="form-item-description">
                  <el-button type="primary" link @click="isTelegramHelpVisible = true">如何获取配置信息？</el-button>
                </div>
              </el-form-item>
              <el-form-item class="form-button-container multi-button">
                <el-button @click="handleTestTelegram" :loading="isTelegramTesting" :disabled="!localTelegramConfig.enabled">
                  发送测试通知
                </el-button>
                <el-button type="success" native-type="submit" :loading="isTelegramSaving">
                  保存通知设置
                </el-button>
              </el-form-item>
            </el-form>
          </transition>
        </el-tab-pane>

        <!-- Trakt.tv 数据增强 -->
        <el-tab-pane label="Trakt.tv" name="trakt">
          <transition mode="out-in">
            <el-form
              v-if="activeTab === 'trakt'"
              ref="traktFormRef"
              :model="localTraktConfig"
              :rules="traktFormRules"
              class="config-section"
              label-position="left"
              :label-width="formLabelWidth"
              @submit.prevent="handleSaveTrakt(traktFormRef)"
              hide-required-asterisk
            >
              <el-form-item label="启用 Trakt.tv">
                <el-switch v-model="localTraktConfig.enabled" />
                <div class="form-item-description">
                  从 Trakt.tv 获取精确到分钟的剧集播出时间，以优化追更中心的“缺失”和“下集”判断逻辑。
                </div>
              </el-form-item>
              <el-form-item label="Client ID" prop="client_id">
                <el-input 
                  v-model="localTraktConfig.client_id" 
                  class="glow-input" 
                  placeholder="在 Trakt.tv 官网创建应用后获取" 
                  :disabled="!localTraktConfig.enabled"
                  show-password
                />
                <div class="form-item-description">
                  <el-button type="primary" link @click="isTraktHelpVisible = true">如何获取 Client ID？</el-button>
                </div>
              </el-form-item>
              <el-form-item class="form-button-container multi-button">
                <el-button @click="handleTestTrakt" :loading="isTraktTesting" :disabled="!localTraktConfig.enabled">
                  测试连接
                </el-button>
                <el-button type="success" native-type="submit" :loading="isTraktSaving">
                  保存 Trakt 设置
                </el-button>
              </el-form-item>
            </el-form>
          </transition>
        </el-tab-pane>
      </el-tabs>
      <!-- --- 修改结束 --- -->

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

    <el-dialog
      v-model="isTelegramHelpVisible"
      title="如何获取 Telegram 配置信息？"
      width="700px"
    >
      <div class="help-content">
        <h4>第1步：获取 Bot Token</h4>
        <p>在 Telegram 中搜索 <code>@BotFather</code>，发送 <code>/newbot</code> 命令创建一个新的机器人，即可获得 Bot Token。</p>
        
        <el-divider />

        <h4>第2步：获取 Chat ID (三种方式)</h4>
        
        <h5>A. 发送给个人：</h5>
        <ol>
          <li>搜索 <code>@userinfobot</code>，点击 "Start"，它会立即返回您的个人 Chat ID。</li>
          <li><b>关键操作：</b> 您必须主动给您自己创建的机器人发送一条消息（例如，发一个 "Hi"），以激活对话。否则机器人无法给您发消息，会导致 "chat not found" 错误。</li>
        </ol>

        <h5>B. 发送给群组：</h5>
        <ol>
          <li>将您创建的机器人添加到目标群组中。</li>
          <li>在群组中发送任意一条消息。</li>
          <li>在浏览器中访问 <code>https://api.telegram.org/bot<你的BotToken>/getUpdates</code> (将 <code><你的BotToken></code> 替换为您的真实Token)。</li>
          <li>在返回的 JSON 数据中，找到 <code>result[...].message.chat.id</code>，这个通常是以 <code>-</code> 开头的数字就是群组的 Chat ID。</li>
        </ol>

        <h5>C. 发送给频道：</h5>
        <ol>
          <li>将您创建的机器人添加为频道的管理员。</li>
          <li>频道的 Chat ID 通常是其公开链接的用户名，例如 <code>@channel_name</code>。</li>
        </ol>
      </div>
      <template #footer>
        <el-button type="primary" @click="isTelegramHelpVisible = false">我明白了</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="isProxyRulesDialogVisible"
      title="自定义代理规则"
      width="80%"
      top="5vh"
    >
      <div class="proxy-rules-dialog-content">
        <el-alert
          title="规则匹配说明"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 20px;"
        >
          <p>
            程序将按以下顺序匹配规则：<b>自定义规则 > 内置规则 > 全局排除列表</b>。一旦命中任何一条规则，将立即做出决策，不再继续匹配。
          </p>
        </el-alert>
        <div class="rules-table-container">
          <el-table :data="proxyRulesForTable" style="width: 100%" height="100%" border>
            <el-table-column label="启用" width="70" align="center">
              <template #default="scope">
                <el-tooltip
                  v-if="scope.row.isBuiltIn"
                  content="请在主配置页面修改内置规则的启用状态"
                  placement="top"
                >
                  <el-checkbox v-model="scope.row.enabled" disabled />
                </el-tooltip>
                <el-checkbox v-else v-model="scope.row.enabled" />
              </template>
            </el-table-column>
            <el-table-column label="备注">
              <template #default="scope">
                <el-input v-model="scope.row.remark" :disabled="scope.row.isBuiltIn" placeholder="例如: GitHub" />
              </template>
            </el-table-column>
            <el-table-column label="URL 关键词">
              <template #default="scope">
                <el-input 
                  v-model="scope.row.keyword" 
                  :disabled="scope.row.isBuiltIn" 
                  :placeholder="scope.row.isBuiltIn ? '' : '例如: github.com | githubusercontent.com 记住分隔符用| 前后空格会自动处理'"
                />
              </template>
            </el-table-column>
            <el-table-column label="当前模式下的行为" width="180" align="center">
              <template #default="scope">
                <el-tag :type="getRuleBehavior(scope.row).type">
                  {{ getRuleBehavior(scope.row).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="scope">
                <el-button
                  v-if="!scope.row.isBuiltIn"
                  type="danger"
                  :icon="Delete"
                  circle
                  @click="deleteCustomRule(scope.$index - 3)"
                />
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-button @click="addCustomRule" :icon="Plus" style="margin-top: 15px;">
          添加自定义规则
        </el-button>
        <el-divider />
        <el-form label-position="top">
          <el-form-item label="高级: 全局排除列表 (最终否决权)">
            <el-input 
              v-model="localProxyConfig.exclude" 
              type="textarea"
              :rows="2"
              class="glow-input" 
              placeholder="例如: example.com,*.another-domain.com"
            />
            <div class="form-item-description">
              无论其他规则如何，只要 URL 包含此处的任何一个关键词，就绝对不会走代理。多个地址用英文逗号(,)隔开。
            </div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isProxyRulesDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmProxyRules">确认</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="isTraktHelpVisible"
      title="如何获取 Trakt.tv Client ID？"
      width="700px"
    >
      <div class="help-content">
        <h4>第1步：注册并登录 Trakt.tv 账户</h4>
        <p>如果您还没有账户，请先访问 <a href="https://trakt.tv/" target="_blank">Trakt.tv</a> 官网进行注册。</p>
        
        <el-divider />

        <h4>第2步：创建新的 API 应用</h4>
        <ol>
          <li>登录后，访问您的 API 应用页面：<a href="https://trakt.tv/oauth/applications" target="_blank">https://trakt.tv/oauth/applications</a>。</li>
          <li>点击 "NEW APPLICATION" 按钮。</li>
          <li>填写应用信息：
            <ul>
              <li><strong>Name:</strong> 随意填写，例如 `Emby-Toolkit`。</li>
              <li><strong>Description:</strong> 选填，可以简单描述用途。</li>
              <li><strong>Redirect URI:</strong> 填写 <code>urn:ietf:wg:oauth:2.0:oob</code>。</li>
              <li><strong>Permissions:</strong> 保持默认的 `/checkin` 即可，我们只需要读取公开数据的权限。</li>
            </ul>
          </li>
          <li>点击 "SAVE APP"。</li>
        </ol>

        <el-divider />

        <h4>第3步：复制 Client ID</h4>
        <p>创建成功后，您会在应用列表中看到您刚刚创建的应用。页面上会直接显示 <strong>Client ID</strong> 和 Client Secret。我们只需要复制 <strong>Client ID</strong> 这一长串字符，并将其粘贴到本工具的输入框中即可。</p>
      </div>
      <template #footer>
        <el-button type="primary" @click="isTraktHelpVisible = false">我明白了</el-button>
      </template>
    </el-dialog>

  </div>
</template>

// === 文件: frontend/src/views/ServerConfigView.vue === //

<script setup>
import { ref, onMounted, watch, computed, reactive } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useDoubanStore } from '@/stores/douban'
import { useTaskStore } from '@/stores/task'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWindowSize } from '@vueuse/core'
import { API_BASE_URL } from '@/config/apiConfig'
import { Delete, Plus, Upload, Download } from '@element-plus/icons-vue'
import _ from 'lodash'

const configStore = useConfigStore()
const doubanStore = useDoubanStore()
const taskStore = useTaskStore()

const serverFormRef = ref(null)
const downloadFormRef = ref(null)
const doubanFormRef = ref(null)
const tmdbFormRef = ref(null)
const proxyFormRef = ref(null)
const doubanFixerFormRef = ref(null)
const telegramFormRef = ref(null)
const traktFormRef = ref(null)
const activeTab = ref('server')

const localServerConfig = ref({ server: '', api_key: '', user_id: '' })
const localDownloadConfig = ref({ download_directory: '', download_behavior: 'skip', directory_naming_rule: 'tmdb_id' , nfo_actor_limit: 20 })
const localTelegramConfig = ref({ enabled: false, bot_token: '', chat_id: '' })
const localTraktConfig = ref({ enabled: false, client_id: '' })
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
  custom_rules: [],
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
const isTelegramSaving = ref(false)
const isTelegramTesting = ref(false)
const isTelegramHelpVisible = ref(false)
const isTraktSaving = ref(false)
const isTraktTesting = ref(false)
const isTraktHelpVisible = ref(false)

const isProxyRulesDialogVisible = ref(false)
const tempCustomRules = ref([])

const proxyTargetDescription = computed(() => {
  if (localProxyConfig.value.mode === 'blacklist') {
    return '当前为黑名单模式，请勾选不走代理的目标。常见设置为：勾选豆瓣和Emby，不勾选TMDB。';
  } else {
    return '当前为白名单模式，请勾选需要走代理的目标。常见设置为：仅勾选TMDB。';
  }
});

const telegramFormRules = reactive({
  bot_token: [{
    validator: (rule, value, callback) => {
      if (localTelegramConfig.value.enabled && !value) {
        callback(new Error('启用通知后，Bot Token 不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }],
  chat_id: [{
    validator: (rule, value, callback) => {
      if (localTelegramConfig.value.enabled && !value) {
        callback(new Error('启用通知后，Chat ID 不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }]
})

const traktFormRules = reactive({
  client_id: [{
    validator: (rule, value, callback) => {
      if (localTraktConfig.value.enabled && !value) {
        callback(new Error('启用 Trakt 后，Client ID 不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }]
})

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
    localTelegramConfig.value = { enabled: false, bot_token: '', chat_id: '', ...newConfig.telegram_config }
    localTraktConfig.value = { enabled: false, client_id: '', ...newConfig.trakt_config }
    localProxyConfig.value = {
      enabled: false, 
      url: '', 
      exclude: '', 
      mode: 'blacklist',
      target_tmdb: false,
      target_douban: true,
      target_emby: true,
      custom_rules: [],
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

const handleExportConfig = () => {
  const exportUrl = `${API_BASE_URL}/api/config/export`;
  window.open(exportUrl, '_blank');
};

const handleImportConfig = () => {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    try {
      await ElMessageBox.confirm(
        '您确定要导入此配置文件吗？这将覆盖所有现有设置，操作不可逆。',
        '警告',
        {
          confirmButtonText: '确认导入',
          cancelButtonText: '取消',
          type: 'warning',
        }
      );

      const result = await configStore.importConfig(file);
      if (result.success) {
        ElMessage.success('配置导入成功！页面即将刷新以应用新设置。');
        setTimeout(() => window.location.reload(), 2000);
      } else {
        ElMessage.error(`导入失败: ${result.message}`);
      }
    } catch (error) {
      // 用户点击了取消
      ElMessage.info('导入操作已取消。');
    }
  };
  input.click();
};

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

const handleSaveTelegram = async (formEl) => {
  if (!formEl) return;
  await formEl.validate(async (valid) => {
    if (valid) {
      isTelegramSaving.value = true;
      const result = await configStore.saveTelegramConfig(localTelegramConfig.value);
      showMessage(result.success ? 'success' : 'error', result.message);
      isTelegramSaving.value = false;
    } else {
      showMessage('warning', '请填写所有必填项！');
      return false;
    }
  });
};

const handleTestTelegram = async () => {
  await telegramFormRef.value.validate(async (valid) => {
    if (valid) {
      isTelegramTesting.value = true;
      const result = await configStore.testTelegramConfig(localTelegramConfig.value);
      showMessage(result.success ? 'success' : 'error', result.message);
      isTelegramTesting.value = false;
    } else {
      showMessage('warning', '请先填写必填项再测试！');
    }
  });
};

const handleSaveTrakt = async (formEl) => {
  if (!formEl) return;
  await formEl.validate(async (valid) => {
    if (valid) {
      isTraktSaving.value = true;
      const result = await configStore.saveTraktConfig(localTraktConfig.value);
      showMessage(result.success ? 'success' : 'error', result.message);
      isTraktSaving.value = false;
    } else {
      showMessage('warning', '请填写所有必填项！');
      return false;
    }
  });
};

const handleTestTrakt = async () => {
  await traktFormRef.value.validate(async (valid) => {
    if (valid) {
      isTraktTesting.value = true;
      const result = await configStore.testTraktConfig(localTraktConfig.value);
      showMessage(result.success ? 'success' : 'error', result.message);
      isTraktTesting.value = false;
    } else {
      showMessage('warning', '请先填写必填项再测试！');
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

const tmdbApiDomain = computed(() => {
  const tmdbConf = localTmdbConfig.value;
  if (tmdbConf.custom_api_domain_enabled && tmdbConf.custom_api_domain) {
    try {
      return new URL(tmdbConf.custom_api_domain).hostname;
    } catch (e) {
      return 'api.themoviedb.org';
    }
  }
  return 'api.themoviedb.org';
});

const proxyRulesForTable = computed(() => {
  const builtInRules = [
    { id: 'tmdb', enabled: localProxyConfig.value.target_tmdb, remark: '内置规则: TMDB', keyword: tmdbApiDomain.value, isBuiltIn: true },
    { id: 'douban', enabled: localProxyConfig.value.target_douban, remark: '内置规则: 豆瓣', keyword: 'douban.com', isBuiltIn: true },
    { id: 'emby', enabled: localProxyConfig.value.target_emby, remark: '内置规则: Emby', keyword: localServerConfig.value.server, isBuiltIn: true },
  ];
  return [...builtInRules, ...tempCustomRules.value];
});

const getRuleBehavior = (rule) => {
  const isWhitelist = localProxyConfig.value.mode === 'whitelist';
  if (rule.enabled) {
    return isWhitelist ? { text: '走代理', type: 'success' } : { text: '不走代理', type: 'danger' };
  } else {
    return isWhitelist ? { text: '不走代理', type: 'info' } : { text: '走代理', type: 'info' };
  }
};

const openProxyRulesDialog = () => {
  tempCustomRules.value = _.cloneDeep(localProxyConfig.value.custom_rules || []);
  isProxyRulesDialogVisible.value = true;
};

const addCustomRule = () => {
  tempCustomRules.value.push({ enabled: true, remark: '', keyword: '' });
};

const deleteCustomRule = (index) => {
  tempCustomRules.value.splice(index, 1);
};

const confirmProxyRules = () => {
  localProxyConfig.value.custom_rules = _.cloneDeep(tempCustomRules.value);
  isProxyRulesDialogVisible.value = false;
};
</script>

/* frontend/src/views/ServerConfigView.vue (style 完整覆盖) */
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
  /* --- 新增 --- */
  display: flex;
  justify-content: space-between;
  align-items: center;
  /* --- 新增结束 --- */
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.header-actions {
  display: flex;
  gap: 15px;
}
.config-tabs {
  margin-top: 20px;
  /* 移除卡片边框 */
  border: none;
  box-shadow: none;
  background: transparent;
}
.config-tabs :deep(.el-tabs__content) {
  padding: 30px 5px; /* 调整内边距 */
  overflow: hidden; /* 配合动画 */
}
.config-tabs :deep(.el-tabs__header) {
  /* 移除 header 区域的边框 */
  border-bottom: 1px solid var(--el-border-color-light);
  margin: 0;
}
.config-tabs :deep(.el-tabs__nav) {
  /* 移除 nav 区域的边框 */
  border: none !important;
}
.config-tabs :deep(.el-tabs__item) {
  height: 50px;
  /* 移除 item 的边框 */
  border: none !important;
}
.config-tabs :deep(.el-tabs__item.is-active) {
  color: var(--custom-theme-color);
}
.config-tabs :deep(.el-tabs__active-bar) {
  background-color: var(--custom-theme-color);
}

/* --- 新增：Tab 切换过渡动画 --- */
.config-tabs :deep(.el-tab-pane) {
  transition: all 0.4s cubic-bezier(0.55, 0, 0.1, 1);
}
.v-enter-active,
.v-leave-active {
  /* 使用 v-enter-active 和 v-leave-active 来定义过渡效果 */
  transition: all 0.4s cubic-bezier(0.55, 0, 0.1, 1);
}
.v-enter-from,
.v-leave-to {
  opacity: 0;
  transform: translateY(20px);
}
/* --- 新增结束 --- */
/* --- 修改结束 --- */

.config-section { 
  /* 移除 margin-bottom，由 Tab 容器控制间距 */
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

.proxy-rules-dialog-content {
  height: 65vh;
  display: flex;
  flex-direction: column;
}
.rules-table-container {
  flex-grow: 1;
  overflow: hidden;
}
.help-content h4 {
  margin-top: 0;
  margin-bottom: 10px;
  color: var(--el-text-color-primary);
}
.help-content p, .help-content li {
  font-size: 14px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
  margin-bottom: 8px;
}
.help-content ol {
  padding-left: 20px;
  margin: 10px 0;
}
.help-content code {
  background-color: var(--el-fill-color);
  padding: 2px 4px;
  border-radius: 4px;
  font-family: 'Courier New', Courier, monospace;
}
</style>