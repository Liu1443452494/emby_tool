<!-- frontend/src/components/TelegramSettingsDialog.vue (完整文件覆盖) -->
<template>
  <el-dialog
    v-model="dialogVisible"
    title="Telegram 通知设置"
    width="600px"
    :close-on-click-modal="false"
    @close="$emit('update:visible', false)"
  >
    <el-form v-if="localConfig" :model="localConfig" label-position="top">
      <el-form-item>
        <template #label>
          <span>启用 Telegram 通知</span>
        </template>
        <el-switch v-model="localConfig.enabled" />
      </el-form-item>

      <el-form-item label="Bot Token" prop="bot_token">
        <el-input 
          v-model="localConfig.bot_token" 
          placeholder="从 @BotFather 获取" 
          :disabled="!localConfig.enabled"
          show-password 
        />
      </el-form-item>

      <el-form-item label="Chat ID" prop="chat_id">
        <el-input 
          v-model="localConfig.chat_id" 
          placeholder="用户、频道或群组的ID" 
          :disabled="!localConfig.enabled"
        />
      </el-form-item>

      <!-- --- 核心修改：更新和细化说明文字 --- -->
      <el-alert
        title="如何获取配置信息？"
        type="info"
        :closable="false"
        show-icon
      >
        <p><strong>第1步：获取 Bot Token</strong></p>
        <p>在 Telegram 中搜索 <strong>@BotFather</strong>，发送 <code>/newbot</code> 命令创建一个新的机器人，即可获得 <strong>Bot Token</strong>。</p>
        
        <p style="margin-top: 15px;"><strong>第2步：获取 Chat ID (三种方式)</strong></p>
        
        <p><strong>A. 发送给个人：</strong></p>
        <ol>
          <li>搜索 <strong>@userinfobot</strong>，点击 "Start"，它会立即返回您的个人 <strong>Chat ID</strong>。</li>
          <li><strong>关键操作：</strong> 您必须主动给您自己创建的机器人发送一条消息（例如，发一个 "Hi"），以激活对话。否则机器人无法给您发消息，会导致 "chat not found" 错误。</li>
        </ol>

        <p><strong>B. 发送给群组：</strong></p>
        <ol>
          <li>将您创建的机器人添加到目标群组中。</li>
          <li>在群组中发送任意一条消息。</li>
          <li>在浏览器中访问 `https://api.telegram.org/bot<你的BotToken>/getUpdates` (将 `<你的BotToken>` 替换为您的真实Token)。</li>
          <li>在返回的 JSON 数据中，找到 `result[...].message.chat.id`，这个通常是以 `-` 开头的数字就是群组的 Chat ID。</li>
        </ol>

        <p><strong>C. 发送给频道：</strong></p>
        <ol>
          <li>将您创建的机器人添加为频道的管理员。</li>
          <li>频道的 Chat ID 通常是其公开链接的用户名，例如 `@channel_name`。</li>
        </ol>
      </el-alert>
      <!-- --- 修改结束 --- -->
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="handleTest" :loading="isTesting" :disabled="!localConfig.enabled">
          发送测试消息
        </el-button>
        <div style="flex-grow: 1"></div>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="isSaving">
          保存
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, reactive } from 'vue';
import { useConfigStore } from '@/stores/config';
import { ElMessage } from 'element-plus';
import _ from 'lodash';

const props = defineProps({
  visible: Boolean,
});
const emit = defineEmits(['update:visible']);

const configStore = useConfigStore();
const dialogVisible = ref(props.visible);
const localConfig = reactive({
  enabled: false,
  bot_token: '',
  chat_id: ''
});

const isSaving = ref(false);
const isTesting = ref(false);

watch(() => configStore.appConfig.telegram_config, (newConfig) => {
  if (newConfig) {
    Object.assign(localConfig, _.cloneDeep(newConfig));
  }
}, { immediate: true, deep: true });

watch(() => props.visible, (val) => {
  dialogVisible.value = val;
  if (val) {
    Object.assign(localConfig, _.cloneDeep(configStore.appConfig.telegram_config));
  }
});

const handleSave = async () => {
  isSaving.value = true;
  const result = await configStore.saveTelegramConfig(localConfig);
  if (result.success) {
    ElMessage.success(result.message);
    dialogVisible.value = false;
  } else {
    ElMessage.error(`保存失败: ${result.message}`);
  }
  isSaving.value = false;
};

const handleTest = async () => {
  if (!localConfig.bot_token || !localConfig.chat_id) {
    ElMessage.warning('请先填写 Bot Token 和 Chat ID！');
    return;
  }
  isTesting.value = true;
  const result = await configStore.testTelegramConfig(localConfig);
  if (result.success) {
    ElMessage.success('测试消息发送成功，请检查您的 Telegram！');
  } else {
    ElMessage.error(`测试失败: ${result.message}`);
  }
  isTesting.value = false;
};
</script>

<style scoped>
.el-alert p, .el-alert ol {
  margin: 5px 0;
  font-size: 13px;
  line-height: 1.6;
}
.el-alert ol {
  padding-left: 20px;
}
.dialog-footer {
  display: flex;
  width: 100%;
}
</style>