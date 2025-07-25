<!-- frontend/src/components/SignInSettingsDialog.vue (完整文件覆盖) -->
<template>
  <el-dialog
    v-model="dialogVisible"
    :title="`${moduleName} - 设置`"
    width="700px"
    :close-on-click-modal="false"
    @close="$emit('update:visible', false)"
  >
    <el-form v-if="localConfig" :model="localConfig" label-position="top">
      <el-form-item label="站点 Cookie">
        <el-input v-model="localConfig.cookie" type="textarea" :rows="3" placeholder="请输入完整的站点Cookie" />
      </el-form-item>
      
      <el-form-item label="随机延迟范围 (秒)">
        <el-input v-model="localConfig.random_delay" placeholder="例如: 1-300" />
        <div class="form-item-description">
          任务触发后，会在此范围内随机等待一段时间再执行。格式为 "最小值-最大值"。
        </div>
      </el-form-item>

      <div class="form-grid">
        <el-form-item label="最大重试次数">
          <el-input-number v-model="localConfig.max_retries" :min="0" />
        </el-form-item>
        <el-form-item label="重试间隔 (秒)">
          <el-input-number v-model="localConfig.retry_interval" :min="1" />
        </el-form-item>
        <el-form-item label="历史保留天数">
          <el-input-number v-model="localConfig.history_days" :min="1" />
        </el-form-item>
      </div>

      <!-- --- 新增 --- -->
      <el-form-item label="通知设置">
        <el-switch v-model="localConfig.send_notification" active-text="任务完成后发送通知" />
        <div class="form-item-description">
          此开关仅在“Emby配置”页面中全局启用了Telegram通知后才生效。
        </div>
      </el-form-item>
      <!-- --- 新增结束 --- -->

      <el-alert
        title="【使用教程】"
        type="info"
        :closable="false"
        show-icon
      >
        <p>1. 登录影巢(hdhive.online)，按F12打开开发者工具。</p>
        <p>2. 切换到"应用(Application)" -> "Cookie"，或"网络(Network)"选项卡，找到发往API的请求。</p>
        <p>3. 复制完整的Cookie字符串。</p>
        <p>4. 确保Cookie中包含 `token` 和 `csrf_access_token` 字段。</p>
        <p>5. 粘贴到上方输入框，启用插件并保存。</p>
        <p>⚠️ 影巢需要代理访问，插件会自动使用系统配置的代理。</p>
      </el-alert>
    </el-form>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="store.isSaving">
          保存
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, reactive } from 'vue';
import { useSignInCenterStore } from '@/stores/signInCenter';
import _ from 'lodash';

const props = defineProps({
  visible: Boolean,
  moduleId: String,
  moduleName: String,
  moduleConfig: Object,
});
const emit = defineEmits(['update:visible', 'config-saved']);

const store = useSignInCenterStore();
const dialogVisible = ref(props.visible);
const localConfig = reactive({});

watch(() => props.moduleConfig, (newConfig) => {
  if (newConfig) {
    // --- 修改：确保新字段有默认值 ---
    const defaultConfig = { send_notification: true };
    Object.assign(localConfig, defaultConfig, _.cloneDeep(newConfig));
    // --- 修改结束 ---
  }
}, { immediate: true });

watch(() => props.visible, (val) => {
  dialogVisible.value = val;
});

const handleSave = async () => {
  const success = await store.saveConfig(props.moduleId, localConfig);
  if (success) {
    emit('config-saved', _.cloneDeep(localConfig));
    dialogVisible.value = false;
  }
};
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0 20px;
}
.el-alert {
  margin-top: 20px;
}
.el-alert p {
  margin: 5px 0;
}
.form-item-description {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-top: 4px;
}
</style>