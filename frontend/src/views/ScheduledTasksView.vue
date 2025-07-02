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

    <!-- 豆瓣海报更新对话框 -->
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

    <!-- 剧集元数据刷新对话框 -->
    <el-dialog
      v-model="isRefresherDialogVisible"
      title="剧集元数据刷新 - 独立配置"
      width="600px"
      :close-on-click-modal="false"
    >
      <div v-if="localRefresherConfig" class="independent-task-config">
        <el-form :model="localRefresherConfig" label-position="top">
          
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

          <el-form-item label="元数据写入方式">
            <el-radio-group v-model="localRefresherConfig.overwrite_metadata">
              <el-radio :value="false">仅补充缺失的元数据</el-radio>
              <el-radio :value="true">覆盖所有元数据</el-radio>
            </el-radio-group>
            <div class="form-item-description">
              “仅补充”模式仅填写空缺的字段。“覆盖所有”模式则会用刮削源的数据替换所有字段。
            </div>
          </el-form-item>

          <el-form-item label="智能跳过">
            <el-switch v-model="localRefresherConfig.skip_if_complete" active-text="开启智能跳过" />
            <div class="form-item-description">
              开启后，如果一个分集已经拥有标题、简介和主图片，任务将自动跳过该分集，以提高效率。
              如果想处理所有剧集，就关闭该按钮
            </div>
          </el-form-item>

           <el-divider />
          <el-form-item label="视频截图 (仅在“工具箱代理刷新”模式下生效)">
            <el-switch v-model="localRefresherConfig.screenshot_enabled" active-text="启用视频截图" />
            <div class="form-item-description">
              当 TMDB 和 Emby 都没有分集图片时，尝试从视频文件（仅支持.strm）直接截图。需要 Docker 容器内已安装 ffmpeg。
            </div>
          </el-form-item>
          
          <div v-if="localRefresherConfig.screenshot_enabled" class="sub-options" style="margin-left: 0; padding-left: 10px;">
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
            <el-form-item label="强制覆盖截图">
              <el-switch v-model="localRefresherConfig.force_overwrite_screenshots" active-text="开启强制覆盖" />
              <div class="form-item-description">
                临时开启此项，任务将无视已存在的截图，强制重新生成。用于在调整截图参数后更新不满意的图片。建议用完后关闭。
              </div>
            </el-form-item>
            <el-form-item label="截图质量模式">
          <el-switch 
            v-model="localRefresherConfig.use_smart_screenshot" 
            active-text="高质量(消耗CPU)"
            inactive-text="快速(单帧)"
          />
          <div class="form-item-description">
            高质量模式会分析1秒内的多帧图像，选择最清晰的一张，效果接近Emby原生截图，但会增加CPU负担。
          </div>
        </el-form-item>

        <el-form-item label="本地截图缓存">
              <el-switch 
                v-model="localRefresherConfig.local_screenshot_caching_enabled" 
                active-text="启用本地缓存"
                :disabled="!localRefresherConfig.screenshot_enabled"
              />
              <div class="form-item-description">
                开启后，新生成的截图会自动保存到本地。下次需要截图时会优先使用本地缓存，避免重复耗时操作。缓存将存放在您配置的豆瓣数据根目录下的 `EpisodeScreenshots` 文件夹内。
              </div>
            </el-form-item>
          </div>
        </el-form>
        <el-divider />
        <div class="backup-section">
          <h4><el-icon><Finished /></el-icon> 存量数据处理工具</h4>
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
      </div>
      <template #footer>
        <el-button @click="isRefresherDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 剧集重命名设置与撤销工具对话框 (新) -->
    <el-dialog
      v-model="isRenamerSettingsDialogVisible"
      title="剧集文件重命名 - 设置"
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

    <!-- 撤销重命名列表对话框 (新) -->
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

  </div>
</template>

<script setup>
import { ref, onMounted, watch, reactive, nextTick } from 'vue';
import { useConfigStore } from '@/stores/config';
import { useMediaStore } from '@/stores/media';
import { useEpisodeRenamerStore } from '@/stores/episodeRenamer';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Setting } from '@element-plus/icons-vue';
import cronstrue from 'cronstrue/i18n';
import _ from 'lodash';

const configStore = useConfigStore();
const mediaStore = useMediaStore();
const renamerStore = useEpisodeRenamerStore();

const definedTasks = ref([
  { id: 'actor_localizer', name: '演员中文化', hasSettings: false },
  { id: 'douban_fixer', name: '豆瓣ID修复器', hasSettings: false },
  { id: 'douban_poster_updater', name: '豆瓣海报更新', hasSettings: true },
  { id: 'episode_refresher', name: '剧集元数据刷新', hasSettings: true },
  { id: 'episode_renamer', name: '剧集文件重命名', hasSettings: true }
]);

const localScope = ref({});
const localTaskStates = reactive({});
const localPosterConfig = ref(null);
const localWebhookConfig = ref(null);
const localRefresherConfig = ref(null);
const isBackuping = ref(false); 
const isSaving = ref(false);
const isTriggering = reactive({});
const isPosterDialogVisible = ref(false);
const isWebhookDialogVisible = ref(false);
const isRefresherDialogVisible = ref(false);
const isSearchDialogVisible = ref(false);
const isRenamerSettingsDialogVisible = ref(false);
const isUndoDialogVisible = ref(false);
const selectedUndoLogs = ref([]);
const searchQuery = ref('');
const searchDialogTableRef = ref(null);
const dialogSelection = ref([]);

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
  if (typeof localRefresherConfig.value.backup_overwrite_local === 'undefined') {
    localRefresherConfig.value.backup_overwrite_local = false;
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
    
    const scope = localScope.value;
    const payload = {
        scope: scope,
        config: localRefresherConfig.value
    };

    // 修正：直接调用新API
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/episode-refresher/backup-screenshots`, {
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
    // 用户点击取消时，error为'cancel'，不显示消息
  } finally {
    isBackuping.value = false;
  }
};

const openSettingsDialog = (taskId) => {
  if (taskId === 'douban_poster_updater') {
    isPosterDialogVisible.value = true;
  } else if (taskId === 'episode_refresher') {
    isRefresherDialogVisible.value = true;
  } else if (taskId === 'episode_renamer') {
    isRenamerSettingsDialogVisible.value = true;
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
</style>