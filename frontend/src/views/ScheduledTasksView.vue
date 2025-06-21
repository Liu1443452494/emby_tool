// frontend/src/views/ScheduledTasksView.vue (完整代码)
<template>
  <div class="scheduled-tasks-page">
    <div class="page-header">
      <h2>定时任务</h2>
      <p>在这里统一配置自动化任务，让工具箱按计划处理新入库的媒体，无需手动干预。</p>
    </div>

    <!-- 通用目标范围配置 -->
    <el-card class="box-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>通用目标范围</span>
          <el-tag type="warning" effect="light">所有定时任务均采用此范围</el-tag>
        </div>
      </template>
      <el-form :model="localScope" label-position="top" class="scope-form">
        <el-radio-group v-model="localScope.mode" class="scope-radio-group">
          <el-radio value="latest">最新入库</el-radio>
          <el-radio value="all">所有媒体库</el-radio>
          <el-radio value="by_type">按媒体类型</el-radio>
          <el-radio value="by_library">按媒体库</el-radio>
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
        </div>
      </el-form>
    </el-card>

    <!-- 任务列表容器 -->
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

    <!-- 所有对话框 (Dialogs) -->
    <!-- Webhook 设置对话框 -->
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

    <!-- 豆瓣海报更新器的设置对话框 -->
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
            <div class="form-item-description">关闭时，工具会记录已更新的海报，避免重复工作。开启后，将无差别覆盖范围内的所有媒体项海报。</div>
          </el-form-item>
          <el-form-item label="地区过滤">
            <el-switch v-model="localPosterConfig.skip_mainland_china" active-text="跳过中国大陆影视" />
            <div class="form-item-description">开启后，若媒体的制片国家/地区包含“中国”，则任务会自动跳过该媒体项。此功能依赖于Emby中正确的“制片国家/地区”信息。</div>
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="isPosterDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, onMounted, watch, reactive, computed } from 'vue';
import { useConfigStore } from '@/stores/config';
import { useMediaStore } from '@/stores/media';
import { ElMessage, ElMessageBox } from 'element-plus';
import _ from 'lodash';
import { Setting } from '@element-plus/icons-vue';
import cronstrue from 'cronstrue/i18n';

const configStore = useConfigStore();
const mediaStore = useMediaStore();

const definedTasks = ref([
  { id: 'actor_localizer', name: '演员中文化', hasSettings: false },
  { id: 'douban_fixer', name: '豆瓣ID修复器', hasSettings: false },
  { id: 'douban_poster_updater', name: '豆瓣海报更新', hasSettings: true }
]);

const localScope = ref({});
const localTaskStates = reactive({});
const localPosterConfig = ref(null);
const localWebhookConfig = ref(null);
const isSaving = ref(false);
const isTriggering = reactive({});
const isPosterDialogVisible = ref(false);
const isWebhookDialogVisible = ref(false);

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

function updateStateFromConfig() {
  localScope.value = _.cloneDeep(configStore.appConfig.scheduled_tasks_config.target_scope);
  localPosterConfig.value = _.cloneDeep(configStore.appConfig.douban_poster_updater_config);
  localWebhookConfig.value = _.cloneDeep(configStore.appConfig.webhook_config);

  // 如果用户没有自定义 URL，则生成一个推荐值
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
  
  const scheduledConfig = {
    target_scope: localScope.value,
    tasks: tasksToSave
  };
  const result1 = await configStore.saveScheduledTasksConfig(scheduledConfig);
  const result2 = await configStore.saveDoubanPosterUpdaterConfig(localPosterConfig.value);
  const result3 = await configStore.saveWebhookConfig(localWebhookConfig.value);

  if (result1.success && result2.success && result3.success) {
    ElMessage.success('所有设置已成功保存！');
  } else {
    ElMessage.error(`保存失败: ${result1.message || result2.message || result3.message}`);
  }
  isSaving.value = false;
};

const handleTriggerOnce = async (taskId) => {
  try {
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

const openSettingsDialog = (taskId) => {
  if (taskId === 'douban_poster_updater') {
    isPosterDialogVisible.value = true;
  }
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
</style>