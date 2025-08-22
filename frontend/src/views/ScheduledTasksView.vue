
<template>
  <div class="scheduled-tasks-page">
    <div class="page-header">
      <h2>定时任务</h2>
      <p>在这里统一配置自动化任务，让工具箱按计划处理新入库的媒体，无需手动干预。</p>
    </div>

    <!-- 通用目标范围配置 -->
    <el-card class="box-card common-scope-area" shadow="never">
      <template #header>
        <div class="card-header">
          <span>通用目标范围</span>
          <el-tag type="warning" effect="light">所有定时任务均采用此范围</el-tag>
        </div>
      </template>
      <el-form :model="localScope" label-position="top" class="scope-form">
        <el-radio-group v-model="localScope.mode" class="scope-radio-group">
          <el-radio value="latest">最新入库</el-radio>
          <el-radio value="favorites">仅收藏</el-radio>
          <el-radio value="all">所有媒体库</el-radio>
          <el-radio value="by_type">按媒体类型</el-radio>
          <el-radio value="by_library">按媒体库</el-radio>
          <el-radio value="by_search">按搜索/ID</el-radio>
        </el-radio-group>

        <div class="sub-options">
          <div v-if="localScope.mode === 'latest'" class="latest-options">
            <el-form-item label="获取最近">
              <el-input-number v-model="localScope.days" :min="1" />
              <span class="option-unit">天内</span>
            </el-form-item>
            <el-form-item label="最多处理">
              <el-input-number v-model="localScope.limit" :min="1" :max="500" />
              <span class="option-unit">条</span>
            </el-form-item>
          </div>
          <div v-if="localScope.mode === 'by_type'">
            <el-radio-group v-model="localScope.media_type">
              <el-radio value="Movie">仅电影</el-radio>
              <el-radio value="Series">仅电视剧</el-radio>
            </el-radio-group>
          </div>
          <div v-if="localScope.mode === 'by_library'">
            <el-select v-model="localScope.library_ids" multiple placeholder="请选择媒体库" style="width: 100%;" filterable>
              <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </div>
          <div v-if="localScope.mode === 'all'">
            <el-input v-model="localScope.library_blacklist" type="textarea" :rows="2" placeholder="输入要排除的媒体库名称，用英文逗号(,)隔开" />
          </div>
          <div v-if="localScope.mode === 'by_search'">
            <el-button @click="isSearchDialogVisible = true">
              选择媒体项...
            </el-button>
            <span class="selection-count-text">已选择 {{ localScope.item_ids.length }} 个项目</span>
          </div>
        </div>
      </el-form>
    </el-card>

    <!-- 任务列表容器 (可滚动区域) -->
    <div class="tasks-area">
      <div class="tasks-container">
        <!-- Webhook 卡片 (独立硬编码) -->
        <el-card v-if="localWebhookConfig" class="box-card task-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div class="task-title-container">
                <span>Webhook 实时处理</span>
                <el-button 
                  :icon="Setting" 
                  circle 
                  text
                  class="settings-button"
                  @click="isWebhookDialogVisible = true"
                />
              </div>
              <el-switch v-model="localWebhookConfig.enabled" />
            </div>
          </template>
          <el-form label-position="top">
           <el-form-item label="Webhook URL (可修改)">
             <el-input v-model="localWebhookConfig.url_override" placeholder="请输入 Emby 能访问到的本工具后端地址">
              <template #append>
                <el-button @click="copyWebhookUrl">复制</el-button>
              </template>
            </el-input>
            <div class="form-item-description">
              实时处理新入库媒体，无需定时。
            </div>
           </el-form-item>
           <div class="action-button-container" style="height: 32px;"></div>
          </el-form>
        </el-card>

        <!-- 定时任务卡片 (v-for 循环) -->
        <el-card v-for="task in definedTasks" :key="task.id" class="box-card task-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div class="task-title-container">
                <span>{{ task.name }}</span>
                <el-button 
                  v-if="task.hasSettings"
                  :icon="Setting" 
                  circle 
                  text
                  class="settings-button"
                  @click="openSettingsDialog(task.id)"
                />
              </div>
              <el-switch v-model="localTaskStates[task.id].enabled" />
            </div>
          </template>
          <el-form label-position="top">
            <el-form-item label="执行周期 (CRON 表达式)">
              <el-input 
                v-model="localTaskStates[task.id].cron" 
                placeholder="例如: 0 3 * * *" 
                :disabled="!localTaskStates[task.id].enabled"
                @input="() => parseCron(localTaskStates[task.id])"
              />
              <div class="form-item-description">
                留空则禁用此任务的定时执行。
                <a href="https://crontab.guru/" target="_blank">CRON表达式帮助</a>
              </div>
              <div v-if="localTaskStates[task.id].cronDescription" class="cron-description" :class="{ 'error': localTaskStates[task.id].cronError }">
                {{ localTaskStates[task.id].cronDescription }}
              </div>
            </el-form-item>
            
            <el-form-item class="action-button-item">
              <el-button 
                type="primary" 
                plain 
                @click="handleTriggerOnce(task.id)"
                :loading="isTriggering[task.id]"
                :disabled="!localTaskStates[task.id].enabled"
              >
                立即执行一次
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </div>
    </div>

    <!-- 保存按钮 (固定在底部) -->
    <div class="save-button-container">
      <el-button type="primary" @click="handleSave" :loading="isSaving">保存所有设置</el-button>
    </div>

    <!-- 按搜索选择媒体对话框 -->
    <el-dialog
      v-model="isSearchDialogVisible"
      title="选择媒体项"
      width="60%"
      top="5vh"
    >
      <div class="search-dialog-content">
        <el-form @submit.prevent="handleSearch" class="search-form">
          <el-input v-model="searchQuery" placeholder="输入标题或ItemID..." clearable />
          <el-button type="primary" native-type="submit" :loading="mediaStore.isLoading">搜索</el-button>
        </el-form>
        <div class="search-results-table" v-loading="mediaStore.isLoading">
          <el-table
            ref="searchDialogTableRef"
            :data="mediaStore.searchResults"
            height="100%"
            @selection-change="handleDialogSelectionChange"
            empty-text="请输入关键词搜索"
          >
            <el-table-column type="selection" width="45" />
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="70" />
          </el-table>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isSearchDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="confirmSearchSelection">
            确认选择 ({{ dialogSelection.length }} 项)
          </el-button>
        </span>
      </template>
    </el-dialog>

    <!-- Webhook 对话框 -->
    <el-dialog
      v-model="isWebhookDialogVisible"
      title="Webhook 实时处理 - 详细配置"
      width="600px"
      :close-on-click-modal="false"
    >
      <div v-if="localWebhookConfig" class="webhook-content">
        <div class="flow-description">
          <p>启用后，当有新媒体添加入库时，将自动触发以下流程：</p>
          <el-steps direction="vertical" :active="4" space="30px">
            <el-step title="获取豆瓣ID" description="检查或运行豆瓣ID修复器，确保媒体有关联ID。" />
            <el-step title="同步豆瓣数据" description="等待豆瓣插件下载数据，并将其增量更新到本地缓存。" />
            <el-step title="演员中文化" description="对新增媒体的演员角色名进行中文化处理。" />
            <el-step title="更新豆瓣海报" description="使用最新的豆瓣海报替换当前海报。" />
          </el-steps>
        </div>
        <el-divider />
        <el-form :model="localWebhookConfig" label-position="top">
          <el-form-item label="初始刮削等待时间 (秒)">
            <el-input-number v-model="localWebhookConfig.initial_wait_time" :min="5" />
            <div class="form-item-description">
              收到通知后，等待 Emby 自动刮削插件（如自带刮削器）运行的时间。
            </div>
          </el-form-item>
          <el-form-item label="豆瓣插件等待时间 (秒)">
            <el-input-number v-model="localWebhookConfig.plugin_wait_time" :min="10" />
            <div class="form-item-description">
              ID修复成功后，等待 Emby 的豆瓣插件下载新元数据文件的时间。
            </div>
          </el-form-item>
        </el-form>
      </div>
       <template #footer>
        <el-button @click="isWebhookDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="isPosterDialogVisible"
      title="豆瓣海报更新 - 独立配置"
      width="500px"
      :close-on-click-modal="false"
    >
      <div v-if="localPosterConfig" class="independent-task-config">
        <el-form :model="localPosterConfig" label-position="top">
          <el-form-item label="处理间隔 (秒)">
            <el-input-number v-model="localPosterConfig.update_interval" :min="0.2" :step="0.1" :precision="1" />
            <div class="form-item-description">处理每个媒体项之间的等待时间，防止请求过于频繁。</div>
          </el-form-item>
          <el-form-item label="覆盖模式">
            <el-switch v-model="localPosterConfig.overwrite_existing" active-text="强制覆盖所有海报" inactive-text="智能判断，不覆盖已是豆瓣海报的媒体" />
            <div class="form-item-description">
              关闭时，工具会记录已更新的海报，避免重复工作。开启后，将无差别覆盖范围内的所有媒体项海报。
            </div>
          </el-form-item>
          <el-form-item label="地区过滤">
            <el-switch v-model="localPosterConfig.skip_mainland_china" active-text="跳过中国大陆影视" />
            <div class="form-item-description">
              开启后，若媒体的制片国家/地区包含“中国”，则任务会自动跳过该媒体项。此功能依赖于Emby中正确的“制片国家/地区”信息。
            </div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="isPosterDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>


    <el-dialog
      v-model="isRefresherDialogVisible"
      title="剧集元数据刷新 - 独立配置"
      width="700px"
      :close-on-click-modal="false"
    >
      <div v-if="localRefresherConfig" class="independent-task-config">
        <el-tabs>
          <el-tab-pane label="基础设置">
            <el-form :model="localRefresherConfig" label-position="top" style="padding-top: 10px;">
              <el-form-item label="刷新模式">
                <el-radio-group v-model="localRefresherConfig.refresh_mode">
                  <el-radio value="emby">通知 Emby 刷新 (默认)</el-radio>
                  <el-radio value="toolbox">工具箱代理刷新</el-radio>
                </el-radio-group>
                <div class="form-item-description">
                  <b>通知 Emby 刷新：</b>由本工具向 Emby 发送刷新指令，Emby 服务器自行连接 TMDB 获取数据。如果您的 Emby 服务器无法访问 TMDB，此模式会失败。<br>
                  <b>工具箱代理刷新：</b>由本工具直接访问 TMDB 获取元数据，然后写入 Emby。此模式可以利用工具箱的代理设置，解决 Emby 无法联网的问题。
                </div>
              </el-form-item>

              <el-form-item label="元数据写入方式 (仅“通知Emby刷新”模式生效)">
                <el-radio-group v-model="localRefresherConfig.overwrite_metadata" :disabled="localRefresherConfig.refresh_mode !== 'emby'">
                  <el-radio :value="false">仅补充缺失的元数据</el-radio>
                  <el-radio :value="true">覆盖所有元数据</el-radio>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="智能跳过">
                <el-switch v-model="localRefresherConfig.skip_if_complete" active-text="开启智能跳过" />
                <div class="form-item-description">
                  开启后，如果一个分集已经拥有标题、简介和非截图类图片，任务将自动跳过该分集，以提高效率。
                </div>
              </el-form-item>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="截图与缓存">
            <el-form :model="localRefresherConfig" label-position="top" style="padding-top: 10px;">
              <el-form-item label="截图功能 (仅“工具箱代理刷新”模式生效)">
                <el-switch v-model="localRefresherConfig.screenshot_enabled" active-text="启用视频截图" :disabled="localRefresherConfig.refresh_mode !== 'toolbox'" />
                <div class="form-item-description">
                  当 TMDB 和 Emby 都没有分集图片时，尝试从视频文件（仅支持.strm）直接截图。需要 Docker 容器内已安装 ffmpeg。
                </div>
              </el-form-item>

              <div v-if="localRefresherConfig.screenshot_enabled" class="sub-options" style="margin-left: 0; padding-left: 10px;">
                <el-form-item label="强制覆盖截图 (临时开关)">
                  <el-switch v-model="localRefresherConfig.force_overwrite_screenshots" active-text="开启强制覆盖" />
                  <div class="form-item-description">
                    开启后将无视所有缓存，强制对范围内的所有分集重新截图。用于参数调整后更新不满意的图片。
                  </div>
                </el-form-item>
                
                <el-alert
                  v-if="localRefresherConfig.force_overwrite_screenshots"
                  title="强制覆盖模式已激活"
                  type="warning"
                  show-icon
                  :closable="false"
                  style="margin-bottom: 20px;"
                >
                  <p>所有缓存设置（远程和本地）将被临时忽略，任务将直接对每个分集进行实时截图。</p>
                </el-alert>

                <el-form-item>
                  <template #label>
                    <span>截图与缓存模式</span>
                    <el-tooltip content="点击查看模式详解" placement="top">
                      <el-button 
                        :icon="QuestionFilled" 
                        circle 
                        text 
                        @click.stop.prevent="isCacheModeHelpVisible = true"
                        class="help-button"
                      />
                    </el-tooltip>
                  </template>
                  <el-radio-group v-model="localRefresherConfig.screenshot_cache_mode" :disabled="localRefresherConfig.force_overwrite_screenshots">
                    <el-radio value="none">无缓存</el-radio>
                    <el-radio value="local">本地文件缓存优先</el-radio>
                    <el-radio value="remote">远程图床优先 (GitHub)</el-radio>
                  </el-radio-group>
                </el-form-item>

                <div v-if="localRefresherConfig.screenshot_cache_mode === 'remote'" class="github-config-section">
                  <el-form-item label="GitHub 仓库 URL">
                    <el-input v-model="localRefresherConfig.github_config.repo_url" placeholder="例如: https://github.com/user/repo" :disabled="localRefresherConfig.force_overwrite_screenshots" @input="parseRepoUrl" />
                    <div v-if="parsedRepoInfo" class="form-item-description">
                      已解析: {{ parsedRepoInfo }} <br>
                      数据库地址: <a :href="dbRawUrl" target="_blank">{{ dbRawUrl }}</a>
                    </div>
                  </el-form-item>
                  <el-form-item label="GitHub 个人访问令牌 (PAT)">
                    <el-input v-model="localRefresherConfig.github_config.personal_access_token" type="password" show-password placeholder="仅在备份到GitHub时需要" :disabled="localRefresherConfig.force_overwrite_screenshots" />
                  </el-form-item>
                  <el-form-item label="远程图床降级策略">
                    <el-switch v-model="localRefresherConfig.github_config.allow_fallback" active-text="远程找不到时，允许降级为实时截图" :disabled="localRefresherConfig.force_overwrite_screenshots" />
                  </el-form-item>
                </div>

                <el-divider>截图参数</el-divider>
                <el-form-item label="截图位置百分比">
                  <el-slider v-model="localRefresherConfig.screenshot_percentage" :min="1" :max="99" show-input />
                  <div class="form-item-description">
                    在视频总时长的哪个位置进行截图。例如，10% 表示在视频开头十分之一处。
                  </div>
                </el-form-item>
                <el-form-item label="保底截图秒数">
                  <el-input-number v-model="localRefresherConfig.screenshot_fallback_seconds" :min="1" />
                  <div class="form-item-description">
                    如果无法获取到视频总时长（例如网络问题），则直接在视频的这个秒数进行截图。
                  </div>
                </el-form-item>
                <el-form-item label="截图操作冷却时间 (秒)">
                  <el-input-number v-model="localRefresherConfig.screenshot_cooldown" :min="0" :step="0.5" :precision="1" />
                  <div class="form-item-description">
                    每次截图（调用ffmpeg）之间的等待时间，用于保护视频源服务器（如网盘）。设为0则不等待。
                  </div>
                </el-form-item>
                <el-form-item label="宽屏截图处理">
                  <el-switch v-model="localRefresherConfig.crop_widescreen_to_16_9" active-text="裁剪为 16:9" />
                  <div class="form-item-description">
                    开启后，会将超宽屏（如 21:9）的截图从两侧裁剪，使其变为 16:9，以优化在 Emby 中的显示效果。
                  </div>
                </el-form-item>
                <el-form-item label="截图质量模式">
                  <el-switch v-model="localRefresherConfig.use_smart_screenshot" active-text="高质量(消耗CPU)" inactive-text="快速(单帧)" />
                  <div class="form-item-description">
                    高质量模式会分析1秒内的多帧图像，选择最清晰的一张，效果接近Emby原生截图，但会增加CPU负担。
                  </div>
                </el-form-item>
              </div>
              <el-divider content-position="left">截图压缩</el-divider>
                <el-form-item label="启用压缩">
                  <el-switch v-model="localRefresherConfig.screenshot_compression_enabled" :disabled="!localRefresherConfig.screenshot_enabled" />
                  <div class="form-item-description">
                    对生成的截图进行压缩，以减小文件体积。
                  </div>
                </el-form-item>
                <el-form-item label="压缩阈值">
                  <el-input-number v-model="localRefresherConfig.screenshot_compression_threshold_kb" :min="0" :step="50" :disabled="!localRefresherConfig.screenshot_enabled || !localRefresherConfig.screenshot_compression_enabled" />
                  <span class="unit-label">KB</span>
                  <div class="form-item-description">
                    当截图文件大小超过此值时，才执行压缩。设为 0 则总是压缩。
                  </div>
                </el-form-item>
                <el-form-item label="压缩模式">
                  <el-radio-group v-model="localRefresherConfig.screenshot_compression_mode" :disabled="!localRefresherConfig.screenshot_enabled || !localRefresherConfig.screenshot_compression_enabled">
                    <el-radio value="quality">质量优先</el-radio>
                    <el-radio value="size">大小优先</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item v-if="localRefresherConfig.screenshot_compression_mode === 'quality'" label="图片质量">
                  <el-slider v-model="localRefresherConfig.screenshot_compression_quality" :min="1" :max="95" show-input :disabled="!localRefresherConfig.screenshot_enabled || !localRefresherConfig.screenshot_compression_enabled" />
                  <div class="form-item-description">
                    设置 JPEG 压缩质量，推荐值 80-90。数值越高，画质越好，文件越大。
                  </div>
                </el-form-item>
                <el-form-item v-if="localRefresherConfig.screenshot_compression_mode === 'size'" label="目标大小">
                  <el-input-number v-model="localRefresherConfig.screenshot_compression_target_kb" :min="10" :step="50" :disabled="!localRefresherConfig.screenshot_enabled || !localRefresherConfig.screenshot_compression_enabled" />
                  <span class="unit-label">KB</span>
                  <div class="form-item-description warning-text">
                    <b><el-icon><WarningFilled /></el-icon> (CPU 消耗高)</b> 此模式会通过多次尝试来逼近目标大小，将显著增加 CPU 占用，请谨慎使用。
                  </div>
                </el-form-item>
            </el-form>
          </el-tab-pane>

          <!-- frontend/src/views/ScheduledTasksView.vue (el-tab-pane 替换) -->
          <el-tab-pane label="备份与恢复">
            <div class="backup-section">
              <h4><el-icon><Finished /></el-icon> 从 Emby 备份到本地</h4>
              <p class="form-item-description">
                如果您是从旧版本升级，或之前未开启本地缓存，可以使用此工具将 Emby 中已存在的截图一次性备份到本地，以备不时之需。
              </p>
              <el-form-item label="备份时覆盖本地已有文件">
                <el-switch v-model="localRefresherConfig.backup_overwrite_local" />
              </el-form-item>
              <el-button 
                type="success" 
                plain 
                @click="handleBackupScreenshots"
                :loading="isBackuping"
              >
                使用通用目标范围立即备份
              </el-button>
            </div>
            <!-- --- 新增：从GitHub恢复 --- -->
            <div class="backup-section">
              <h4><el-icon><Download /></el-icon> 从 GitHub 恢复到 Emby</h4>
              <p class="form-item-description">
                此功能将根据您选择的“通用目标范围”，从远程 GitHub 仓库中查找匹配的截图并恢复到 Emby。
              </p>
              <el-form-item label="恢复时覆盖 Emby 上已存在的图片">
                <el-switch v-model="overwriteOnRestore" />
              </el-form-item>
              <el-button 
                type="primary" 
                plain 
                @click="handleRestoreFromGithub"
                :loading="isRestoreFromGithubRunning"
              >
                使用通用目标范围恢复截图
              </el-button>
            </div>
            <!-- --- 新增结束 --- -->
            <div class="backup-section">
              <h4><el-icon><Upload /></el-icon> 从本地备份到 GitHub</h4>
              <p class="form-item-description">
                此工具会将您本地 `EpisodeScreenshots` 文件夹中的所有截图，增量上传到您配置的 GitHub 仓库。仅限已配置 PAT 的维护者使用。
              </p>
              <el-form-item label="下载冷却时间 (秒)">
                <el-input-number v-model="localRefresherConfig.github_config.download_cooldown" :min="0" :step="0.1" :precision="1" />
                <div class="form-item-description">
                  每次从 GitHub 下载文件（如 database.json）前的等待时间。
                </div>
              </el-form-item>
              <el-form-item label="上传冷却时间 (秒)">
                <el-input-number v-model="localRefresherConfig.github_config.upload_cooldown" :min="0" :step="0.1" :precision="1" />
                <div class="form-item-description">
                  每次向 GitHub 上传文件（截图或索引）前的等待时间。
                </div>
              </el-form-item>
              <el-form-item label="备份时覆盖远程同名文件">
                <el-switch v-model="localRefresherConfig.github_config.overwrite_remote" />
              </el-form-item>
              <el-button 
                type="primary" 
                plain 
                @click="handleBackupToGithub"
                :loading="isGithubBackuping"
                :disabled="!localRefresherConfig.github_config.personal_access_token"
              >
                开始备份到 GitHub
              </el-button>
            </div>
            <div class="backup-section">
              <h4><el-icon><Aim /></el-icon> 精准覆盖 GitHub 截图</h4>
              <p class="form-item-description">
                当您对远程图床上的某些截图不满意时，可以在本地手动重新截图后，使用此工具选择特定分集，将本地的新截图上传以覆盖远程的旧截图。
              </p>
              <el-button 
                type="danger" 
                plain 
                @click="openPreciseUpdateDialog"
                :disabled="!localRefresherConfig.github_config.personal_access_token"
              >
                打开精准覆盖工具
              </el-button>
            </div>
            <div class="backup-section">
          <h4><el-icon><Delete /></el-icon> 清理远程作废截图</h4>
          <p class="form-item-description">
            当 TMDB 提供了官方图后，之前备份到 GitHub 的社区截图就成了作废文件。此功能可以安全地清理这些文件。
          </p>
          <el-form-item label="删除冷却时间 (秒)">
            <el-input-number v-model="localRefresherConfig.github_config.delete_cooldown" :min="0" :step="0.1" :precision="1" />
            <div class="form-item-description">
              每次从 GitHub 删除文件前的等待时间，以避免API速率限制。
            </div>
          </el-form-item>
          <div style="display: flex; gap: 15px;">
            <el-button 
              type="primary" 
              plain 
              @click="isReviewDialogVisible = true"
            >
              审核待删除列表
            </el-button>
            <el-button 
              type="danger" 
              plain 
              @click="handleCleanupGithub"
              :loading="isGithubCleanupRunning"
              :disabled="!localRefresherConfig.github_config.personal_access_token"
            >
              开始清理
            </el-button>
          </div>
        </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="isRefresherDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新增：缓存模式帮助说明对话框 -->
    <el-dialog
      v-model="isCacheModeHelpVisible"
      title="截图与缓存模式详解"
      width="650px"
    >
      <div class="help-content">
        <h4>无缓存</h4>
        <p>不使用任何缓存。每次需要图片时，都会直接从视频文件实时截图。适用于测试或不希望在本地留下任何文件的场景。</p>
        
        <el-divider />

        <h4>本地文件缓存优先</h4>
        <p><strong>推荐“生产者”或纯本地用户使用。</strong></p>
        <ul>
          <li><strong>工作流</strong>: 优先在本地 `EpisodeScreenshots` 文件夹中查找截图。如果找不到，则进行实时截图，并将新截图**保存到本地**。</li>
          <li><strong>优点</strong>: 截图生成和读取速度快，不依赖网络。适合系统性地为剧集制作截图，并为后续备份到 GitHub 做准备。</li>
          <li><strong>缺点</strong>: 会占用本地磁盘空间。</li>
        </ul>

        <el-divider />

        <h4>远程图床优先 (GitHub)</h4>
        <p><strong>推荐“消费者”或希望节省本地空间的维护者使用。</strong></p>
        <ul>
          <li><strong>工作流</strong>: 优先从您配置的 GitHub 仓库查找图片。如果找不到，会降级查找**本地缓存**。如果本地也找不到，最终会进行**实时截图**。</li>
          <li><strong>作为普通用户 (未填写PAT)</strong>: 新生成的截图仅上传至 Emby，**不会**在本地保存任何文件，实现零空间占用。</li>
          <li><strong>作为维护者 (已填写PAT)</strong>: 新生成的截图会被**暂存到本地**，方便您后续统一使用“备份到GitHub”功能进行同步。</li>
        </ul>
      </div>
      <template #footer>
        <el-button type="primary" @click="isCacheModeHelpVisible = false">我明白了</el-button>
      </template>
    </el-dialog>

    <!-- 剧集重命名设置与撤销工具对话框 -->
    <el-dialog
      v-model="isRenamerSettingsDialogVisible"
      title="文件重命名 - 通用设置"
      width="700px"
    >
      <div class="independent-task-config">
        <el-alert 
          title="核心前提：一致的路径映射" 
          type="warning" 
          :closable="false" 
          show-icon
          style="margin-bottom: 20px;"
        >
          <p>
            为了让本工具能正确地找到并重命名您的 <code>.strm</code> 文件，您必须确保 <strong>Emby 容器</strong> 和 <strong>Emby-Toolkit 容器</strong> 的媒体目录挂载点完全一致。
          </p>
        </el-alert>
        
        <h4>正确配置示例 (docker-compose.yml)</h4>
        <p class="form-item-description">
          请检查您的 <code>docker-compose.yml</code> 文件，确保两个服务中的 <code>volumes</code> 媒体路径部分是相同的。
        </p>
        <pre class="code-example">
services:
  emby:
    # ... emby的其他配置 ...
    volumes:
      - /path/on/your/host/media:/media  # <-- Emby的挂载点

  emby-toolkit-backend:
    # ... 工具箱的其他配置 ...
    volumes:
      - ./data:/app/data
      - /path/on/your/host/media:/media  # <-- 工具箱的挂载点，必须与上方一致
      # ... 其他可能的挂载 ...
</pre>
        <el-divider />
        <div style="text-align: center;">
          <el-button type="danger" plain @click="openUndoDialog">打开撤销工具</el-button>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="isRenamerSettingsDialogVisible = false">我明白了</el-button>
      </template>
    </el-dialog>

    <!-- 撤销重命名列表对话框 -->
    <el-dialog
      v-model="isUndoDialogVisible"
      title="撤销本地文件重命名"
      width="70%"
      top="5vh"
      destroy-on-close
    >
      <div class="undo-dialog-content">
        <el-alert 
          title="警告" 
          type="warning" 
          show-icon 
          :closable="false"
          style="margin-bottom: 15px;"
        >
          <p>此操作将把本地文件恢复到重命名之前的状态。这可能会导致 Emby 媒体库中的项目暂时失效，建议操作完成后手动扫描媒体库。</p>
          <p><strong>此工具仅操作本地文件，不会操作您的网盘文件。</strong></p>
        </el-alert>
        <div class="undo-toolbar">
          <el-button @click="renamerStore.fetchLogs()" :loading="renamerStore.isLoading">刷新列表</el-button>
        </div>
        <div class="undo-table-container" v-loading="renamerStore.isLoading">
          <el-table
            :data="renamerStore.logs"
            height="100%"
            @selection-change="handleUndoSelectionChange"
            empty-text="没有找到任何重命名记录"
          >
            <el-table-column type="selection" width="55" />
            <el-table-column label="新文件名 (将被撤销)" min-width="300">
              <template #default="scope">
                <span class="filename new-filename">{{ getBaseName(scope.row.new_base_path) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="旧文件名 (将恢复为)" min-width="300">
              <template #default="scope">
                <span class="filename">{{ getBaseName(scope.row.old_base_path) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="scope">
                <el-tag :type="scope.row.status === 'completed' ? 'success' : 'primary'">
                  {{ scope.row.status === 'completed' ? '已同步网盘' : '仅本地重命名' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="记录时间" width="180">
              <template #default="scope">
                {{ new Date(scope.row.timestamp).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
      <template #footer>
        <el-button @click="isUndoDialogVisible = false">关闭</el-button>
        <el-button 
          type="danger" 
          @click="handleUndo" 
          :disabled="selectedUndoLogs.length === 0"
          :loading="renamerStore.isApplying"
        >
          撤销选中项 ({{ selectedUndoLogs.length }})
        </el-button>
      </template>
    </el-dialog>

    <!-- 新增：精准覆盖对话框 -->
    <el-dialog
      v-model="isPreciseUpdateDialogVisible"
      title="精准覆盖 GitHub 截图"
      width="80%"
      top="5vh"
      destroy-on-close
    >
      <div class="precise-update-dialog-content">
        <!-- 步骤一：搜索 -->
        <div class="step-container">
          <div class="step-header">
            <div class="step-number">1</div>
            <h4>搜索剧集</h4>
          </div>
          <el-form @submit.prevent="handlePreciseSearch" class="search-form">
            <el-input v-model="preciseSearchQuery" placeholder="输入剧集标题或ID..." clearable />
            <el-button type="primary" native-type="submit" :loading="mediaStore.isLoading">搜索 Emby</el-button>
          </el-form>
          <div class="search-results-table" v-loading="mediaStore.isLoading">
            <el-table
              :data="mediaStore.searchResults"
              height="100%"
              highlight-current-row
              @current-change="handlePreciseSeriesSelection"
              empty-text="请输入关键词搜索"
            >
              <el-table-column prop="Name" label="标题" show-overflow-tooltip />
              <el-table-column prop="ProductionYear" label="年份" width="70" />
              <el-table-column label="TMDB ID" width="120">
                <template #default="scope">
                  {{ getProviderId(scope.row, 'tmdb') || 'N/A' }}
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <!-- 步骤二：选择分集 -->
        <div class="step-container">
          <div class="step-header">
            <div class="step-number">2</div>
            <h4>选择要更新的分集</h4>
          </div>
          <div class="episodes-table-container" v-loading="isFetchingEpisodes">
            <el-table
              :data="episodesForSelection"
              height="100%"
              @selection-change="handlePreciseEpisodeSelection"
              empty-text="请先在左侧选择一部剧集"
            >
              <el-table-column type="selection" width="55" />
              <el-table-column label="季" prop="ParentIndexNumber" width="60" />
              <el-table-column label="集" prop="IndexNumber" width="60" />
              <el-table-column label="标题" prop="Name" show-overflow-tooltip />
            </el-table>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="isPreciseUpdateDialogVisible = false">关闭</el-button>
        <el-button 
          type="danger" 
          @click="handlePreciseUpdate" 
          :disabled="selectedEpisodes.length === 0"
          :loading="isPreciseUpdating"
        >
          开始更新选中的 ({{ selectedEpisodes.length }}) 项
        </el-button>
      </template>
    </el-dialog>
<DeletionReviewDialog v-model:visible="isReviewDialogVisible" />
<el-dialog
      v-model="isEpisodeRoleSyncDialogVisible"
      title="剧集角色同步到分集 - 独立配置"
      width="600px"
      :close-on-click-modal="false"
    >
      <div v-if="localEpisodeRoleSyncConfig" class="independent-task-config">
        <el-alert 
          title="功能说明" 
          type="info" 
          :closable="false" 
          show-icon
          style="margin-bottom: 20px;"
        >
          <p>
            此功能会读取“演员角色映射”页面生成的 <code>actor_role_map.json</code> 文件，并将其中已确认的中文角色名，批量应用到对应剧集的所有分集中。
          </p>
        </el-alert>
        <el-form :model="localEpisodeRoleSyncConfig" label-position="top">
          <el-form-item label="每个分集处理的演员数量上限">
            <el-input-number v-model="localEpisodeRoleSyncConfig.actor_limit" :min="1" :max="200" />
            <div class="form-item-description">对每一个分集都应用此限制，仅处理该集的前 N 位演员。</div>
          </el-form-item>
          <el-form-item label="降级策略">
            <el-switch v-model="localEpisodeRoleSyncConfig.fallback_to_actor_string" active-text="启用" />
            <div class="form-item-description">
              当一个分集演员在角色映射表和豆瓣数据中都找不到匹配时，如果启用此项，会将其角色名强制替换为“演员”；否则将保持英文原样。
            </div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="isEpisodeRoleSyncDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
<!-- --- 新增结束 --- -->
  </div>
</template>

<script setup>
import { ref, onMounted, watch, reactive, nextTick, computed } from 'vue';
import { useConfigStore } from '@/stores/config';
import { useMediaStore } from '@/stores/media';
import { useEpisodeRenamerStore } from '@/stores/episodeRenamer';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Setting, ArrowDown, Finished, Upload, QuestionFilled, Aim, Delete, Download, WarningFilled } from '@element-plus/icons-vue';
import DeletionReviewDialog from '@/components/DeletionReviewDialog.vue'; 
import cronstrue from 'cronstrue/i18n';
import _ from 'lodash';
import { API_BASE_URL } from '@/config/apiConfig';

const configStore = useConfigStore();
const mediaStore = useMediaStore();
const renamerStore = useEpisodeRenamerStore();

const definedTasks = ref([
  { id: 'actor_localizer', name: '演员中文化', hasSettings: false },
  { id: 'douban_fixer', name: '豆瓣ID修复器', hasSettings: false },
  { id: 'douban_poster_updater', name: '豆瓣海报更新', hasSettings: true },
  { id: 'episode_refresher', name: '剧集元数据刷新', hasSettings: true },
  { id: 'episode_renamer', name: '剧集文件重命名', hasSettings: true },
  { id: 'movie_renamer', name: '电影文件重命名', hasSettings: true },
  { id: 'episode_role_sync', name: '剧集角色同步到分集', hasSettings: true },
  { id: 'id_mapper', name: 'TMDB-Emby ID 映射表', hasSettings: false }
]);

const localScope = ref({});
const localTaskStates = reactive({});
const localPosterConfig = ref(null);
const localWebhookConfig = ref(null);
const localRefresherConfig = ref(null);
const localEpisodeRoleSyncConfig = ref(null);
const isEpisodeRoleSyncDialogVisible = ref(false);
const isBackuping = ref(false); 
const isGithubBackuping = ref(false);
const isSaving = ref(false);
const isTriggering = reactive({});
const isPosterDialogVisible = ref(false);
const isWebhookDialogVisible = ref(false);
const isRefresherDialogVisible = ref(false);
const isSearchDialogVisible = ref(false);
const isRenamerSettingsDialogVisible = ref(false);
const isCacheModeHelpVisible = ref(false);
const isUndoDialogVisible = ref(false);
const selectedUndoLogs = ref([]);
const searchQuery = ref('');
const isReviewDialogVisible = ref(false);
const searchDialogTableRef = ref(null);
const dialogSelection = ref([]);
const parsedRepoInfo = ref('');
const dbRawUrl = ref('');

// 新增：精准覆盖功能相关状态
const isPreciseUpdateDialogVisible = ref(false);
const preciseSearchQuery = ref('');
const selectedSeriesForPreciseUpdate = ref(null);
const isFetchingEpisodes = ref(false);
const episodesForSelection = ref([]);
const selectedEpisodes = ref([]);
const isPreciseUpdating = ref(false);
const isGithubCleanupRunning = ref(false);
const overwriteOnRestore = ref(false);
const isRestoreFromGithubRunning = ref(false);


definedTasks.value.forEach(taskDef => {
  localTaskStates[taskDef.id] = {
    id: taskDef.id,
    name: taskDef.name,
    enabled: false,
    cron: '',
    cronDescription: '',
    cronError: false,
  };
  isTriggering[taskDef.id] = false;
});

onMounted(() => {
  mediaStore.fetchLibraries();
  watch(() => configStore.isLoaded, (loaded) => {
    if (loaded) {
      updateStateFromConfig();
    }
  }, { immediate: true });
});

watch(isSearchDialogVisible, (visible) => {
  if (visible) {
    nextTick(() => {
      const selectedIds = new Set(localScope.value.item_ids);
      mediaStore.searchResults.forEach(row => {
        if (selectedIds.has(row.Id)) {
          searchDialogTableRef.value?.toggleRowSelection(row, true);
        }
      });
    });
  }
});

function updateStateFromConfig() {
  localScope.value = _.cloneDeep(configStore.appConfig.scheduled_tasks_config.target_scope);
  localPosterConfig.value = _.cloneDeep(configStore.appConfig.douban_poster_updater_config);
  localWebhookConfig.value = _.cloneDeep(configStore.appConfig.webhook_config);
  localRefresherConfig.value = _.cloneDeep(configStore.appConfig.episode_refresher_config);
  localEpisodeRoleSyncConfig.value = _.cloneDeep(configStore.appConfig.episode_role_sync_config);
  
  if (localRefresherConfig.value.github_config?.repo_url) {
    parseRepoUrl();
  }

  if (localWebhookConfig.value && !localWebhookConfig.value.url_override) {
    const baseUrl = window.location.origin;
    localWebhookConfig.value.url_override = `${baseUrl}/api/webhook/emby`;
  }

  const savedTasks = configStore.appConfig.scheduled_tasks_config.tasks;
  
  savedTasks.forEach(savedTask => {
    if (localTaskStates[savedTask.id]) {
      Object.assign(localTaskStates[savedTask.id], savedTask);
      parseCron(localTaskStates[savedTask.id]);
    }
  });

  definedTasks.value.forEach(taskDef => {
    if (!savedTasks.some(st => st.id === taskDef.id)) {
      Object.assign(localTaskStates[taskDef.id], {
        enabled: false,
        cron: '',
      });
    }
  });
}

const handleSave = async () => {
  isSaving.value = true;
  
  const tasksToSave = Object.values(localTaskStates).map(task => {
    const { cronDescription, cronError, ...rest } = task;
    return rest;
  });
  
  const scopeToSave = { ...localScope.value };
  if (!scopeToSave.item_ids) {
    scopeToSave.item_ids = [];
  }
  
  const scheduledConfig = {
    target_scope: scopeToSave,
    tasks: tasksToSave
  };
  const result1 = await configStore.saveScheduledTasksConfig(scheduledConfig);
  const result2 = await configStore.saveDoubanPosterUpdaterConfig(localPosterConfig.value);
  const result3 = await configStore.saveWebhookConfig(localWebhookConfig.value);
  const result4 = await configStore.saveEpisodeRefresherConfig(localRefresherConfig.value);
  const result5 = await configStore.saveEpisodeRoleSyncConfig(localEpisodeRoleSyncConfig.value);

  if (result1.success && result2.success && result3.success && result4.success) {
    ElMessage.success('所有设置已成功保存！');
  } else {
    ElMessage.error(`保存失败: ${result1.message || result2.message || result3.message || result4.message}`);
  }
  isSaving.value = false;
};

const handleTriggerOnce = async (taskId) => {
  try {
    if (localScope.value.mode === 'by_search' && localScope.value.item_ids.length === 0) {
      ElMessage.warning('在“按搜索/ID”模式下，请先搜索并勾选至少一个媒体项。');
      return;
    }
    await ElMessageBox.confirm(
      '即将使用当前已保存的通用目标范围配置立即执行一次此任务。确定吗？',
      '确认操作',
      {
        confirmButtonText: '确定执行',
        cancelButtonText: '取消',
        type: 'info',
      }
    );
    
    isTriggering[taskId] = true;
    const result = await configStore.triggerScheduledTaskOnce(taskId);
    if (result.success) {
      ElMessage.success(result.message);
    } else {
      ElMessage.error(`触发失败: ${result.message}`);
    }
  } catch (error) {
    // 用户点击了取消
  } finally {
    isTriggering[taskId] = false;
  }
};


const handleBackupScreenshots = async () => {
  try {
    await ElMessageBox.confirm(
      '即将使用当前选择的通用目标范围，扫描并备份所有已存在的截图到本地。此过程可能需要较长时间，是否继续？',
      '确认备份操作',
      {
        confirmButtonText: '开始备份',
        cancelButtonText: '取消',
        type: 'info',
      }
    );
    
    isBackuping.value = true;
    
    const payload = {
        scope: localScope.value,
        config: localRefresherConfig.value
    };

    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/backup-screenshots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动备份任务失败');
    
    ElMessage.success(data.message);

  } catch (error) {
    if (error && error.message) {
      ElMessage.error(`启动备份失败: ${error.message}`);
    }
  } finally {
    isBackuping.value = false;
  }
};

const handleBackupToGithub = async () => {
  try {
    await ElMessageBox.confirm(
      '即将开始备份本地截图到 GitHub。此操作会扫描本地所有截图，与远程数据库对比，并上传差异文件。此过程可能消耗大量时间和网络流量，是否继续？',
      '确认备份到 GitHub',
      {
        confirmButtonText: '开始备份',
        cancelButtonText: '取消',
        type: 'info',
      }
    );
    
    isGithubBackuping.value = true;
    
    const payload = {
        config: localRefresherConfig.value
    };

    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/backup-to-github`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动备份任务失败');
    
    ElMessage.success(data.message);

  } catch (error) {
    if (error && error.message) {
      ElMessage.error(`启动备份失败: ${error.message}`);
    }
  } finally {
    isGithubBackuping.value = false;
  }
};

const openSettingsDialog = (taskId) => {
  if (taskId === 'douban_poster_updater') {
    isPosterDialogVisible.value = true;
  } else if (taskId === 'episode_refresher') {
    isRefresherDialogVisible.value = true;
  } else if (taskId === 'episode_renamer' || taskId === 'movie_renamer') { // 复用条件
    isRenamerSettingsDialogVisible.value = true;
  } else if (taskId === 'episode_role_sync') {
    isEpisodeRoleSyncDialogVisible.value = true;
  }
};

const openUndoDialog = () => {
  isRenamerSettingsDialogVisible.value = false;
  isUndoDialogVisible.value = true;
  renamerStore.fetchLogs();
};

const parseCron = (task) => {
  if (!task || !task.cron || task.cron.trim() === '') {
    if(task) task.cronDescription = '';
    if(task) task.cronError = false;
    return;
  }
  try {
    task.cronDescription = cronstrue.toString(task.cron, { locale: "zh_CN" });
    task.cronError = false;
  } catch (e) {
    task.cronDescription = `表达式无效: ${e}`;
    task.cronError = true;
  }
};

const copyWebhookUrl = async () => {
  try {
    await navigator.clipboard.writeText(localWebhookConfig.value.url_override);
    ElMessage.success('Webhook URL 已成功复制到剪贴板！');
  } catch (err) {
    ElMessage.error('复制失败，您的浏览器可能不支持此功能。');
  }
};

const handleSearch = () => {
  mediaStore.searchMedia(searchQuery.value);
};

const handleDialogSelectionChange = (selection) => {
  dialogSelection.value = selection;
};

const confirmSearchSelection = () => {
  localScope.value.item_ids = dialogSelection.value.map(item => item.Id);
  isSearchDialogVisible.value = false;
};

const handleUndoSelectionChange = (selection) => {
  selectedUndoLogs.value = selection;
};

const handleUndo = async () => {
  try {
    await ElMessageBox.confirm(
      `即将对选中的 ${selectedUndoLogs.value.length} 个项目执行撤销操作，文件将被重命名回旧名称。此操作可能导致Emby媒体库项目丢失，建议操作后手动扫描媒体库。是否继续？`,
      '确认撤销操作',
      { confirmButtonText: '确定撤销', cancelButtonText: '取消', type: 'warning' }
    );
    await renamerStore.startUndoTask(selectedUndoLogs.value);
    isUndoDialogVisible.value = false;
  } catch (error) {
    // 用户取消
  }
};

const getBaseName = (path) => {
  if (!path) return '';
  return path.split(/[\\/]/).pop();
};

const parseRepoUrl = () => {
  const url = localRefresherConfig.value.github_config.repo_url;
  const match = url.match(/github\.com\/([^/]+)\/([^/]+)/);
  if (match) {
    const owner = match[1];
    const repo = match[2].replace(/\.git$/, '');
    parsedRepoInfo.value = `${owner}/${repo}`;
    dbRawUrl.value = `https://raw.githubusercontent.com/${owner}/${repo}/main/database.json`;
  } else {
    parsedRepoInfo.value = '';
    dbRawUrl.value = '';
  }
};

const getProviderId = (row, providerName) => {
  if (!row.ProviderIds) return null;
  const lowerProviderName = providerName.toLowerCase();
  const providerKey = Object.keys(row.ProviderIds).find(key => key.toLowerCase() === lowerProviderName);
  return providerKey ? row.ProviderIds[providerKey] : null;
};

// --- 新增：精准覆盖相关函数 ---
const openPreciseUpdateDialog = () => {
  isPreciseUpdateDialogVisible.value = true;
  preciseSearchQuery.value = '';
  mediaStore.searchResults = [];
  selectedSeriesForPreciseUpdate.value = null;
  episodesForSelection.value = [];
  selectedEpisodes.value = [];
};

const handleCleanupGithub = async () => {
  try {
    await ElMessageBox.confirm(
      '即将根据待删除列表，在后台清理远程文件。此操作不可逆，是否继续？',
      '确认清理操作',
      {
        confirmButtonText: '开始清理',
        cancelButtonText: '取消',
        type: 'warning',
      }
    );
    
    isGithubCleanupRunning.value = true;
    
    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/cleanup-github`, {
        method: 'POST',
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动清理任务失败');
    
    ElMessage.success(data.message);

  } catch (error) {
    if (error && error.message) {
      ElMessage.error(`启动清理失败: ${error.message}`);
    }
  } finally {
    isGithubCleanupRunning.value = false;
  }
};

// frontend/src/views/ScheduledTasksView.vue (新增函数)

const handleRestoreFromGithub = async () => {
  try {
    await ElMessageBox.confirm(
      '即将根据您选择的“通用目标范围”，从远程 GitHub 仓库恢复截图。此操作可能会下载大量图片并写入您的Emby，是否继续？',
      '确认恢复操作',
      {
        confirmButtonText: '开始恢复',
        cancelButtonText: '取消',
        type: 'info',
      }
    );
    
    isRestoreFromGithubRunning.value = true;
    
    const payload = {
        scope: localScope.value,
        overwrite: overwriteOnRestore.value
    };

    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/restore-from-github`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动恢复任务失败');
    
    ElMessage.success(data.message);

  } catch (error) {
    if (error && error.message) {
      ElMessage.error(`启动恢复失败: ${error.message}`);
    }
  } finally {
    isRestoreFromGithubRunning.value = false;
  }
};

const handlePreciseSearch = () => {
  mediaStore.searchMedia(preciseSearchQuery.value);
};

const handlePreciseSeriesSelection = async (series) => {
  if (!series) {
    selectedSeriesForPreciseUpdate.value = null;
    episodesForSelection.value = [];
    return;
  }
  
  const tmdbId = getProviderId(series, 'tmdb');
  if (!tmdbId) {
    ElMessage.warning('该剧集缺少 TMDB ID，无法进行后续操作。');
    selectedSeriesForPreciseUpdate.value = null;
    episodesForSelection.value = [];
    return;
  }

  selectedSeriesForPreciseUpdate.value = series;
  isFetchingEpisodes.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/series/${series.Id}/local-screenshots`);
    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || '获取分集列表失败');
    }
    const episodes = await response.json();
    if (episodes.length === 0) {
      ElMessage.info('该剧集在本地没有找到任何可用于覆盖的截图文件。');
    }
    episodesForSelection.value = _.sortBy(episodes, ['ParentIndexNumber', 'IndexNumber']);
  } catch (error) {
    ElMessage.error(`获取分集列表失败: ${error.message}`);
    episodesForSelection.value = [];
  } finally {
    isFetchingEpisodes.value = false;
  }
};

const handlePreciseEpisodeSelection = (selection) => {
  selectedEpisodes.value = selection;
};

const handlePreciseUpdate = async () => {
  if (selectedEpisodes.value.length === 0) {
    ElMessage.warning('请至少选择一个分集进行更新。');
    return;
  }

  try {
    await ElMessageBox.confirm(
      `即将为您选中的 ${selectedEpisodes.value.length} 个分集，从本地查找新截图并上传覆盖到 GitHub。请确保您已在本地准备好了新的截图文件。是否继续？`,
      '确认精准覆盖操作',
      { confirmButtonText: '开始更新', cancelButtonText: '取消', type: 'info' }
    );

    isPreciseUpdating.value = true;
    const payload = {
      series_tmdb_id: getProviderId(selectedSeriesForPreciseUpdate.value, 'tmdb'),
      series_name: selectedSeriesForPreciseUpdate.value.Name,
      episodes: selectedEpisodes.value.map(ep => ({
        season_number: ep.ParentIndexNumber,
        episode_number: ep.IndexNumber
      })),
      config: localRefresherConfig.value
    };

    const response = await fetch(`${API_BASE_URL}/api/episode-refresher/precise-upload-from-local`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '启动任务失败');
    
    ElMessage.success(data.message);
    isPreciseUpdateDialogVisible.value = false;

  } catch (error) {
    if (error && error.message) {
      ElMessage.error(`启动任务失败: ${error.message}`);
    }
  } finally {
    isPreciseUpdating.value = false;
  }
};
</script>

<style scoped>
.scheduled-tasks-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
  --custom-theme-color-active: #4a8a7f;
}

.scheduled-tasks-page {
  padding: 0 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-header, .common-scope-area, .save-button-container {
  flex-shrink: 0;
}

.tasks-area {
  flex-grow: 1;
  overflow-y: auto;
  padding-bottom: 20px;
}

.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.box-card {
  margin-top: 20px;
  border: 1px solid var(--el-border-color-lighter);
}
.common-scope-area {
  margin-top: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}
.scope-form {
  padding-top: 10px;
}
.scope-radio-group {
  margin-bottom: 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 15px;
}
.sub-options {
  padding-left: 10px;
  border-left: 2px solid var(--el-border-color-lighter);
}
.latest-options {
  display: flex;
  gap: 30px;
  align-items: center;
}
.latest-options .el-form-item {
  margin-bottom: 0;
}
.option-unit {
  margin-left: 10px;
  color: var(--el-text-color-regular);
}
.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}
.form-item-description a {
  color: var(--el-color-primary);
  text-decoration: none;
}
.form-item-description a:hover {
  text-decoration: underline;
}

.tasks-container {
  margin-top: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
}

.action-button-container {
  margin-top: 15px;
  text-align: right;
}

.save-button-container {
  padding: 20px 0;
  text-align: center;
  border-top: 1px solid var(--el-border-color-light);
}
.save-button-container .el-button {
  width: 300px;
}

.scheduled-tasks-page :deep(.el-button--primary) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
  --el-button-active-bg-color: var(--custom-theme-color-active);
  --el-button-active-border-color: var(--custom-theme-color-active);
}
.scheduled-tasks-page :deep(.el-radio__input.is-checked .el-radio__inner),
.scheduled-tasks-page :deep(.el-switch.is-checked .el-switch__core) {
  border-color: var(--custom-theme-color);
  background: var(--custom-theme-color);
}
.scheduled-tasks-page :deep(.el-radio__input.is-checked+.el-radio__label) {
  color: var(--custom-theme-color);
}
.scheduled-tasks-page :deep(.el-input__wrapper:focus),
.scheduled-tasks-page :deep(.el-textarea__inner:focus) {
  border-color: var(--custom-theme-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
}
.scheduled-tasks-page :deep(.el-select .el-tag) {
  --el-tag-bg-color: color-mix(in srgb, var(--custom-theme-color) 20%, transparent);
  --el-tag-border-color: color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
  --el-tag-text-color: var(--custom-theme-color);
}
.scheduled-tasks-page :deep(.el-select .el-tag .el-tag__close) {
  color: var(--custom-theme-color);
}
.scheduled-tasks-page :deep(.el-select .el-tag .el-tag__close:hover) {
  background-color: var(--custom-theme-color);
  color: white;
}

.scheduled-tasks-page :deep(.el-button--primary.is-plain) {
  --el-button-text-color: var(--custom-theme-color);
  --el-button-bg-color: color-mix(in srgb, var(--custom-theme-color) 10%, transparent);
  --el-button-border-color: color-mix(in srgb, var(--custom-theme-color) 40%, transparent);
}
.scheduled-tasks-page :deep(.el-button--primary.is-plain:hover) {
  --el-button-hover-text-color: #ffffff;
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
}
.task-title-container {
  display: flex;
  align-items: center;
  gap: 8px;
}
.settings-button {
  font-size: 16px;
  color: var(--el-text-color-secondary);
}
.settings-button:hover {
  color: var(--custom-theme-color);
}

.cron-description {
  font-size: 12px;
  color: var(--el-color-success);
  margin-top: 5px;
  padding: 5px 8px;
  background-color: var(--el-color-success-light-9);
  border-radius: 4px;
  line-height: 1.4;
}

.cron-description.error {
  color: var(--el-color-error);
  background-color: var(--el-color-error-light-9);
}

.webhook-content {
  padding-top: 10px;
}

.flow-description {
  background-color: var(--el-fill-color-light);
  padding: 15px 20px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.flow-description p {
  margin: 0 0 15px 0;
  color: var(--el-text-color-regular);
}

.flow-description :deep(.el-step__title.is-finish) {
  color: var(--el-color-success);
}
.flow-description :deep(.el-step__head.is-finish) {
  color: var(--el-color-success);
  border-color: var(--el-color-success);
}

.box-card .el-form {
  min-height: 120px;
}

.action-button-item {
  display: flex;
  justify-content: flex-end;
}
.action-button-item :deep(.el-form-item__content) {
  justify-content: flex-end;
  margin-left: 0 !important;
}

.action-button-item-placeholder {
  margin-bottom: 0;
  height: 40px;
}

.independent-task-config {
  padding-top: 10px;
}

.search-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
  height: 65vh;
}
.search-form {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.search-results-table {
  flex-grow: 1;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}
.selection-count-text {
  margin-left: 15px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.undo-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 15px;
  height: 65vh;
}
.undo-toolbar {
  flex-shrink: 0;
}
.undo-table-container {
  flex-grow: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}
.filename {
  font-family: 'Courier New', Courier, monospace;
}
.new-filename {
  color: var(--el-color-error);
}
.code-example {
  background-color: var(--el-fill-color);
  padding: 10px;
  border-radius: 4px;
  margin-top: 10px;
  font-family: 'Courier New', Courier, monospace;
  white-space: pre-wrap;
}
.backup-section {
  margin-top: 20px;
  padding: 15px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background-color: var(--el-fill-color-lighter);
}
.backup-section h4 {
  margin: 0 0 10px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.backup-section .el-form-item {
  margin-bottom: 15px;
}
.github-config-section {
  padding: 15px;
  margin-top: 15px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.help-button {
  margin-left: 8px;
  color: var(--el-text-color-placeholder);
}
.help-content h4 {
  margin-top: 0;
  margin-bottom: 10px;
  color: var(--el-text-color-primary);
}
.help-content p {
  font-size: 14px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
  margin: 0 0 10px 0;
}
.help-content ul {
  padding-left: 20px;
  margin: 0;
}
.help-content li {
  margin-bottom: 8px;
}

/* 新增：精准覆盖对话框样式 */
.precise-update-dialog-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  height: 70vh;
}
.step-container {
  display: flex;
  flex-direction: column;
  gap: 15px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 15px;
}
.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.step-number {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background-color: var(--custom-theme-color);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
}
.step-header h4 {
  margin: 0;
  font-size: 1.1rem;
}
.episodes-table-container {
  flex-grow: 1;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}.unit-label {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
}

.warning-text {
  color: var(--el-color-warning);
  display: flex;
  align-items: center;
  gap: 5px;
}
</style>