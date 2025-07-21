<!-- frontend/src/components/SignInCard.vue (完整文件覆盖 - 简化版) -->
<template>
  <el-card class="box-card task-card" shadow="never">
    <template #header>
      <div class="card-header">
        <div class="task-title-container">
          <span>{{ moduleData.name }}</span>
        </div>
        <div class="header-actions">
          <el-switch v-model="localConfig.enabled" />
          <el-dropdown trigger="click">
            <el-button :icon="MoreFilled" circle text class="more-button" />
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :icon="Setting" @click="isSettingsDialogVisible = true">设置</el-dropdown-item>
                <el-dropdown-item :icon="Refresh" @click="handleReset">重置数据</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </template>
    
    <el-form :model="localConfig" label-position="top" class="card-form">
     <el-form-item label="执行周期 (CRON 表达式)">
        <el-input 
          v-model="localConfig.cron" 
          placeholder="例如: 0 8 * * *" 
          :disabled="!localConfig.enabled"
        />
        <div class="form-item-description">
          留空则禁用此任务的定时执行。
          <a href="https://crontab.guru/" target="_blank">CRON表达式帮助</a>
          <!-- --- 新增：CRON 描述 --- -->
          <span v-if="cronDescription.text" class="cron-description" :class="{ 'error': cronDescription.error }">
            {{ cronDescription.text }}
          </span>
          <!-- --- 新增结束 --- -->
        </div>
      </el-form-item>
      
      <div class="action-button-container">
        <el-button 
          type="primary" 
          plain 
          @click="handleTrigger"
          :disabled="!localConfig.enabled"
        >
          立即执行一次
        </el-button>
      </div>
    </el-form>

    <SignInSettingsDialog
      v-if="isSettingsDialogVisible"
      v-model:visible="isSettingsDialogVisible"
      :module-id="moduleData.id"
      :module-name="moduleData.name"
      :module-config="localConfig"
      @config-saved="handleConfigUpdate"
    />
  </el-card>
</template>

<script setup>
// frontend/src/components/SignInCard.vue (script setup 替换)

import { ref, reactive, watch, defineAsyncComponent, computed } from 'vue';
import { useSignInCenterStore } from '@/stores/signInCenter';
import { MoreFilled, Setting, Refresh } from '@element-plus/icons-vue';
import _ from 'lodash';
// --- 新增：导入 cronstrue ---
import cronstrue from 'cronstrue/i18n';
// --- 新增结束 ---

const props = defineProps({
  moduleData: {
    type: Object,
    required: true,
  },
});

const store = useSignInCenterStore();
const localConfig = reactive({});
const isSettingsDialogVisible = ref(false);

const SignInSettingsDialog = defineAsyncComponent(() => import('./SignInSettingsDialog.vue'));

// --- 新增：CRON 表达式描述的计算属性 ---
const cronDescription = computed(() => {
  if (!localConfig.cron || localConfig.cron.trim() === '') {
    return { text: '', error: false };
  }
  try {
    // 使用中文解析
    const description = cronstrue.toString(localConfig.cron, { locale: "zh_CN" });
    return { text: description, error: false };
  } catch (e) {
    return { text: `表达式无效: ${e}`, error: true };
  }
});
// --- 新增结束 ---

watch(() => props.moduleData, (newData) => {
  if (newData && newData.config) {
    Object.assign(localConfig, _.cloneDeep(newData.config));
  }
}, { immediate: true, deep: true });

const debouncedSave = _.debounce(async () => {
  await store.saveConfig(props.moduleData.id, localConfig);
}, 1000);

watch(() => [localConfig.enabled, localConfig.cron], () => {
  debouncedSave();
});

const handleTrigger = () => {
  store.triggerSignIn(props.moduleData.id);
};

const handleReset = () => {
  store.resetData(props.moduleData.id, props.moduleData.name);
};

const handleConfigUpdate = (newConfig) => {
  Object.assign(localConfig, newConfig);
  store.saveConfig(props.moduleData.id, localConfig);
};
</script>

<style scoped>
.task-card {
  border: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-direction: column;
  height: 260px; /* 减小固定高度 */
}
.task-card :deep(.el-card__header) {
  padding: 15px 20px;
  flex-shrink: 0;
}
.task-card :deep(.el-card__body) {
  padding: 20px;
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.task-title-container {
  font-weight: bold;
  font-size: 1.1rem;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.more-button {
  font-size: 18px;
  color: var(--el-text-color-secondary);
}
.card-form {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
}
.card-form .el-form-item {
  margin-bottom: 18px;
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
.action-button-container {
  margin-top: auto;
  padding-top: 10px;
  text-align: right;
  border-top: 1px solid var(--el-border-color-lighter);
}.cron-description {
  font-size: 12px;
  color: var(--el-color-success);
  margin-top: 5px;
  padding: 5px 8px;
  background-color: var(--el-color-success-light-9);
  border-radius: 4px;
  line-height: 1.4;
  display: inline-block; /* 让背景色包裹文字 */
}

.cron-description.error {
  color: var(--el-color-error);
  background-color: var(--el-color-error-light-9);
}
</style>