// frontend/src/views/ActorLocalizerView.vue (完整代码)
<template>
  <div class="actor-localizer-page">
    <div class="main-layout">
      <div class="controls-panel">
        <div class="config-area">
          <el-tabs v-model="activeTab" class="config-tabs">
            <!-- 执行目标 Tab -->
            <el-tab-pane label="执行目标" name="target">
              <div class="tab-content">
                <el-radio-group v-model="targetScope" class="scope-radio-group">
                  <el-radio value="media_type">按媒体类型</el-radio>
                  <el-radio value="library">按媒体库</el-radio>
                  <el-radio value="all_libraries">所有媒体库</el-radio>
                  <el-radio value="search">按标题/ID搜索</el-radio>
                </el-radio-group>
                <div class="sub-options">
                  <div v-if="targetScope === 'media_type'">
                    <el-radio-group v-model="targetMediaType">
                      <el-radio value="Movie">仅电影</el-radio>
                      <el-radio value="Series">仅电视剧</el-radio>
                    </el-radio-group>
                  </div>
                  <div v-if="targetScope === 'library'">
                    <el-select v-model="targetLibraryIds" multiple placeholder="请选择媒体库" style="width: 100%;" filterable>
                      <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name" :value="item.id" />
                    </el-select>
                  </div>
                  <div v-if="targetScope === 'all_libraries'">
                    <el-input v-model="targetLibraryBlacklist" type="textarea" :rows="2" placeholder="输入要排除的媒体库名称，用英文逗号(,)隔开" class="glow-input" />
                  </div>
                  <div v-if="targetScope === 'search'">
                    <el-form @submit.prevent="handleSearch" class="search-form">
                      <el-input v-model="searchQuery" placeholder="输入标题或ItemID..." clearable class="glow-input" />
                      <el-button type="primary" native-type="submit" :loading="actorStore.isSearching">搜索</el-button>
                    </el-form>
                  </div>
                </div>
              </div>
              
              <div class="search-results-area" v-if="targetScope === 'search'">
                <div class="divider"></div>
                <h3 class="area-title">搜索结果 (请勾选)</h3>
                <div class="table-wrapper">
                  <div v-if="actorStore.isSearching" class="table-skeleton-wrapper">
                    <el-skeleton :rows="5" animated />
                  </div>
                  <el-table v-else ref="searchTableRef" :data="actorStore.searchResults" style="width: 100%" height="100%" @selection-change="handleSelectionChange">
                    <el-table-column type="selection" width="40" />
                    <el-table-column prop="Name" label="标题" />
                    <el-table-column prop="ProductionYear" label="年份" width="70" />
                  </el-table>
                </div>
              </div>

            </el-tab-pane>
            <!-- 高级设置 Tab -->
            <el-tab-pane label="高级设置" name="settings">
              <div class="tab-content">
                <el-form label-position="top">
                  <el-form-item label="纯英文角色名处理">
                    <el-switch v-model="localConfig.replace_english_role" active-text="暴力替换为“演员”" inactive-text="保持原样" />
                    <div class="form-item-description">当豆瓣中无匹配时，将纯英文角色名强制替换为“演员”。</div>
                  </el-form-item>
                  <el-form-item label="豆瓣英文替换emby英文角色">
                    <el-switch v-model="localConfig.enhance_english_role_with_douban" active-text="启用" />
                    <div class="form-item-description">
                      开启后，会使用豆瓣更丰富的英文角色名（如 "Spider-Man / Peter Parker"）覆盖 Emby 中较简单的英文名（如 "Spider-Man"），以便为后续翻译提供更完整的原文。
                    </div>
                  </el-form-item>
                  <el-form-item label="豆瓣通用角色名处理">
                    <el-switch v-model="localConfig.ignore_generic_douban_roles" active-text="忽略豆瓣中的通用角色名" />
                    <div class="form-item-description">开启后，如果豆瓣提供的角色名在下方黑名单中，则放弃该匹配，继续尝试翻译引擎。</div>
                  </el-form-item>
                  <el-form-item v-if="localConfig.ignore_generic_douban_roles" label="通用角色名黑名单">
                    <el-select
                      v-model="localConfig.generic_role_blacklist"
                      multiple
                      filterable
                      allow-create
                      default-first-option
                      placeholder="输入要忽略的词语后按回车"
                      style="width: 100%;"
                    >
                    </el-select>
                  </el-form-item>
                  <el-form-item label="处理数量上限">
                    <el-input-number v-model="localConfig.person_limit" :min="1" :max="100" />
                    <div class="form-item-description">为提高效率，仅处理每个媒体项的前 N 位演职员。</div>
                  </el-form-item>
                  
                  <div class="divider"></div>
                  <h3>翻译引擎设置</h3>
                  <el-form-item>
                    <el-switch v-model="localConfig.translation_enabled" active-text="启用翻译引擎" />
                    <div class="form-item-description">当豆瓣匹配和暴力替换都失败后，使用翻译引擎作为最终手段。</div>
                  </el-form-item>
                  <div v-if="localConfig.translation_enabled">
                    <el-form-item label="翻译模式">
                      <el-radio-group v-model="localConfig.translation_mode">
                        <el-radio value="translators">第三方库</el-radio>
                        <el-radio value="tencent">腾讯云API</el-radio>
                        <el-radio value="siliconflow">AI大模型</el-radio>
                      </el-radio-group>
                    </el-form-item>
                    <el-form-item v-if="localConfig.translation_mode === 'translators'" label="翻译引擎">
                      <el-select v-model="localConfig.translator_engine" placeholder="请选择引擎">
                        <el-option label="Baidu" value="baidu" />
                        <el-option label="Google" value="google" />
                        <el-option label="Alibaba" value="alibaba" />
                      </el-select>
                    </el-form-item>
                    <el-form-item v-if="localConfig.translation_mode === 'tencent'">
                      <el-button @click="showTencentDialog = true">配置腾讯云 API</el-button>
                    </el-form-item>
                    <el-form-item v-if="localConfig.translation_mode === 'siliconflow'">
                      <el-button @click="showSiliconflowDialog = true">配置 AI 大模型 API</el-button>
                    </el-form-item>
                    <el-form-item label="API调用冷却">
                       <el-switch v-model="localConfig.api_cooldown_enabled" active-text="启用" />
                       <el-input-number v-if="localConfig.api_cooldown_enabled" v-model="localConfig.api_cooldown_time" :precision="1" :step="0.1" :min="0" />
                       <span v-if="localConfig.api_cooldown_enabled" style="margin-left: 10px;">秒</span>
                    </el-form-item>
                  </div>

                  <div class="divider"></div>
                  <h3>自动化设置</h3>
                  <el-form-item label="定时自动应用 (CRON)">
                    <el-input v-model="localConfig.apply_cron" class="glow-input" placeholder="例如: 0 5 * * * (每天凌晨5点)" />
                    <div class="form-item-description">
                      使用CRON表达式定时执行全量扫描并直接应用修改，跳过预览步骤。留空则禁用。
                    </div>
                  </el-form-item>
                  <el-form-item>
                    <el-button 
                      type="warning" 
                      @click="handleDirectApply" 
                      :loading="actorStore.isLoading"
                      :disabled="!!actorStore.activePreviewTaskId || !!actorStore.activeApplyTaskId"
                      plain
                    >
                      立即执行一次自动应用
                    </el-button>
                  </el-form-item>

                </el-form>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
        
        <div class="action-area">
          <div class="divider"></div>
          <h3 class="area-title">执行操作</h3>
          <div class="button-grid">
            <el-button v-if="!actorStore.activePreviewTaskId" @click="handlePreview" :loading="actorStore.isLoading" :disabled="!!actorStore.activeApplyTaskId">预览修改</el-button>
            <el-button v-else type="warning" @click="handleStopTask(actorStore.activePreviewTaskId)">停止预览</el-button>
            <el-button v-if="!actorStore.activeApplyTaskId" type="danger" @click="handleApply" :loading="actorStore.isLoading" :disabled="!canApply">应用修改</el-button>
            <el-button v-else type="danger" @click="handleStopTask(actorStore.activeApplyTaskId)">停止应用</el-button>
          </div>
          <el-button 
            @click="isCorrectionDialogVisible = true" 
            style="width: 100%; margin-top: 15px;"
            plain
          >
            手动校正角色名 (AI辅助)
          </el-button>
          <el-button 
            type="success" 
            @click="handleSaveConfig" 
            :loading="isSaving" 
            style="width: 100%; margin-top: 15px;"
          >
            保存所有设置
          </el-button>
        </div>
      </div>
      <div class="results-panel">
        <h3 class="area-title">控制台日志</h3>
        <div class="console-output">
          <pre>{{ actorStore.consoleOutput || '预览或应用结果将显示在这里...' }}</pre>
        </div>
      </div>
    </div>

    <TencentApiConfigDialog 
      v-if="localConfig.tencent_config"
      v-model:visible="showTencentDialog"
      :config="localConfig.tencent_config"
      @save="(newConfig) => localConfig.tencent_config = newConfig"
    />
    <SiliconflowApiConfigDialog
      v-if="localConfig.siliconflow_config"
      v-model:visible="showSiliconflowDialog"
      :config="localConfig.siliconflow_config"
      @save="(newConfig) => localConfig.siliconflow_config = newConfig"
    />
    <ActorRoleCorrectionDialog v-model:visible="isCorrectionDialogVisible" />
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed, reactive } from 'vue';
import { useActorLocalizerStore } from '@/stores/actorLocalizer';
import { useConfigStore } from '@/stores/config';
import { useTaskStore } from '@/stores/task';
import { useMediaStore } from '@/stores/media';
import { ElMessageBox, ElMessage } from 'element-plus';
import _ from 'lodash';
import { useStorage } from '@vueuse/core';
import TencentApiConfigDialog from '@/components/TencentApiConfigDialog.vue';
import SiliconflowApiConfigDialog from '@/components/SiliconflowApiConfigDialog.vue';
import ActorRoleCorrectionDialog from '@/components/ActorRoleCorrectionDialog.vue';

const actorStore = useActorLocalizerStore();
const isCorrectionDialogVisible = ref(false);
const configStore = useConfigStore();
const taskStore = useTaskStore();
const mediaStore = useMediaStore();

const activeTab = ref('target');
const searchQuery = ref('');
const selectedItems = ref([]);
const searchTableRef = ref(null);

const showTencentDialog = ref(false);
const showSiliconflowDialog = ref(false);
const isSaving = ref(false);

const localConfig = ref({});

const targetScope = useStorage('actor-target-scope', 'media_type');
const targetMediaType = useStorage('actor-target-media-type', 'Movie');
const targetLibraryIds = useStorage('actor-target-library-ids', []);
const targetLibraryBlacklist = useStorage('actor-target-library-blacklist', '');

const canApply = computed(() => actorStore.previewResults.length > 0 && !actorStore.activePreviewTaskId && !actorStore.activeApplyTaskId);

onMounted(() => {
  // 使用 deep clone 避免响应式对象互相影响
  localConfig.value = _.cloneDeep(configStore.appConfig.actor_localizer_config);
  mediaStore.fetchLibraries();
  taskStore.connect();
});

watch(() => configStore.appConfig.actor_localizer_config, (newGlobalConfig) => {
  // 仅当外部配置变化时，才更新本地配置
  if (!_.isEqual(newGlobalConfig, localConfig.value)) {
    localConfig.value = _.cloneDeep(newGlobalConfig);
  }
}, { deep: true });

watch(() => localConfig.value.replace_english_role, (newValue) => {
  if (newValue && localConfig.value.translation_enabled) {
    localConfig.value.translation_enabled = false;
    ElMessage.info('已自动禁用翻译引擎，因为暴力替换优先级更高。');
  }
});

watch(() => localConfig.value.translation_enabled, (newValue) => {
  if (newValue && localConfig.value.replace_english_role) {
    localConfig.value.replace_english_role = false;
    ElMessage.info('已自动禁用暴力替换，因为翻译引擎优先级更高。');
  }
});

watch(targetScope, (newScope) => {
  if (newScope !== 'search') {
    actorStore.searchResults = [];
    if (searchTableRef.value) searchTableRef.value.clearSelection();
  }
});

const handleSearch = async () => {
  await actorStore.searchMedia(searchQuery.value);
};

const handleSelectionChange = (val) => {
  selectedItems.value = val;
};

const handlePreview = () => {
  actorStore.clearResults();
  actorStore.resetState();

  const finalTarget = {
    scope: targetScope.value,
    media_type: targetMediaType.value,
    library_ids: targetLibraryIds.value,
    library_blacklist: targetLibraryBlacklist.value,
    item_ids: [],
  };

  if (finalTarget.scope === 'search') {
    if (selectedItems.value.length === 0) {
      ElMessage.warning('请在搜索结果中勾选至少一个项目。');
      return;
    }
    finalTarget.item_ids = selectedItems.value.map(item => item.Id);
  }

  actorStore.startPreview({ target: finalTarget, config: localConfig.value });
};

const handleApply = async () => {
  try {
    await ElMessageBox.confirm(`即将对 ${actorStore.previewResults.length} 个媒体项应用角色名修改。此操作不可逆，是否继续？`, '确认操作', { confirmButtonText: '确定应用', cancelButtonText: '取消', type: 'warning' });
    actorStore.startApply();
  } catch (error) { /* 用户点击取消 */ }
};

const handleDirectApply = async () => {
  try {
    await ElMessageBox.confirm(
      '此操作将扫描所有媒体库并直接应用修改，不会进行预览。确定要立即执行吗？',
      '确认操作',
      { 
        confirmButtonText: '立即执行', 
        cancelButtonText: '取消', 
        type: 'warning' 
      }
    );
    actorStore.startDirectApply();
  } catch (error) {
    // 用户点击取消
  }
};

const handleStopTask = async (taskId) => {
  if (taskId) await taskStore.cancelTask(taskId);
};

const handleSaveConfig = async () => {
  isSaving.value = true;
  const result = await configStore.saveActorLocalizerConfig(localConfig.value);
  if (result.success) {
    ElMessage.success('所有设置已成功保存！');
  } else {
    ElMessage.error(`保存失败: ${result.message}`);
  }
  isSaving.value = false;
};
</script>

<style scoped>
.actor-localizer-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
  --custom-theme-color-active: #4a8a7f;
  height: 100%;
  overflow: hidden;
}
.main-layout {
  display: grid;
  grid-template-columns: 420px 1fr;
  height: 100%;
  width: 100%;
}
.controls-panel {
  display: grid;
  grid-template-rows: 1fr auto;
  padding: 20px;
  border-right: 1px solid var(--el-border-color-light);
  overflow: hidden;
}
.config-area {
  overflow-y: auto;
  padding-right: 10px;
  display: flex;
  flex-direction: column;
}
.search-results-area {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 150px;
  padding-top: 20px;
  flex-grow: 1;
}
.action-area {
  flex-shrink: 0;
  padding-top: 20px;
}
.results-panel {
  padding: 20px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.console-output {
  flex-grow: 1;
  overflow-y: auto;
  background-color: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Courier New', Courier, monospace;
  font-size: 14px;
  border-radius: 4px;
  padding: 15px;
  border: 1px solid var(--el-border-color-darker);
}
.console-output pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.table-wrapper {
  flex-grow: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}
.table-skeleton-wrapper {
  padding: 20px;
  height: 100%;
  box-sizing: border-box;
}
.tab-content {
  padding: 10px 5px;
}
.scope-radio-group {
  display: flex;
  flex-wrap: wrap;
  gap: 15px;
  margin-bottom: 20px;
}
.sub-options {
  display: flex;
  flex-direction: column;
  gap: 15px;
  padding-left: 10px;
  border-left: 2px solid var(--el-border-color-lighter);
}
.search-form {
  display: flex;
  gap: 10px;
}
.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}
.divider {
  border-top: 1px solid var(--el-border-color-lighter);
  margin-bottom: 20px;
}
.area-title {
  margin: 0 0 15px 0;
  font-size: 1.1rem;
  font-weight: bold;
  color: var(--custom-theme-color);
}
.results-panel .area-title {
  color: var(--el-text-color-primary);
}
.button-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 15px;
}
.button-grid .el-button {
  width: 100%;
  margin: 0 !important;
}
:deep(.el-tabs) {
  display: flex;
  flex-direction: column;
  height: 100%;
}
:deep(.el-tabs__content) {
  flex-grow: 1;
  overflow-y: auto;
}
:deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
}
:deep(.el-tabs__header) {
  margin-bottom: 20px;
}

.actor-localizer-page :deep(.el-button--primary) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
  --el-button-active-bg-color: var(--custom-theme-color-active);
  --el-button-active-border-color: var(--custom-theme-color-active);
}
.actor-localizer-page :deep(.el-button--success) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
}
.actor-localizer-page :deep(.el-radio__input.is-checked .el-radio__inner),
.actor-localizer-page :deep(.el-switch.is-checked .el-switch__core) {
  border-color: var(--custom-theme-color);
  background: var(--custom-theme-color);
}
.actor-localizer-page :deep(.el-radio__input.is-checked+.el-radio__label) {
  color: var(--custom-theme-color);
}
.actor-localizer-page :deep(.glow-input .el-input__wrapper:hover),
.actor-localizer-page :deep(.el-textarea__inner:hover) { 
  border-color: var(--custom-theme-color); 
}
.actor-localizer-page :deep(.glow-input.is-focus .el-input__wrapper),
.actor-localizer-page :deep(.el-textarea__inner:focus) {
  border-color: var(--custom-theme-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
}
.actor-localizer-page :deep(.el-select .el-tag) {
  --el-tag-bg-color: color-mix(in srgb, var(--custom-theme-color) 20%, transparent);
  --el-tag-border-color: color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
  --el-tag-text-color: var(--custom-theme-color);
}
.actor-localizer-page :deep(.el-select .el-tag .el-tag__close) {
  color: var(--custom-theme-color);
}
.actor-localizer-page :deep(.el-select .el-tag .el-tag__close:hover) {
  background-color: var(--custom-theme-color);
  color: white;
}
.actor-localizer-page :deep(.el-tabs__item.is-active) {
  color: var(--custom-theme-color);
}
.actor-localizer-page :deep(.el-tabs__active-bar) {
  background-color: var(--custom-theme-color);
}
.actor-localizer-page :deep(.el-table__row .el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: var(--custom-theme-color);
  border-color: var(--custom-theme-color);
}
</style>