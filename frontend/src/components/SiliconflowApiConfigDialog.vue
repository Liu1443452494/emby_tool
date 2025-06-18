// frontend/src/components/SiliconflowApiConfigDialog.vue (新文件)
<template>
  <el-dialog
    :model-value="visible"
    title="AI大模型 (SiliconFlow) API 配置"
    width="600px"
    @update:model-value="$emit('update:visible', $event)"
    :close-on-click-modal="false"
  >
    <el-form :model="localConfig" label-position="top">
      <el-form-item label="API Key (Bearer Token)">
        <el-input v-model="localConfig.api_key" placeholder="请输入 SiliconFlow API Key" show-password />
      </el-form-item>
      <el-form-item label="使用的模型">
        <el-select v-model="localConfig.model_name" placeholder="请选择或输入模型名称" style="width: 100%;" filterable allow-create>
          <el-option v-for="(remark, name) in defaultModels" :key="name" :label="`${name} ${remark}`" :value="name" />
        </el-select>
      </el-form-item>
    </el-form>
    <div v-if="testResult" :class="['test-result', testResult.success ? 'success' : 'error']">
      {{ testResult.message }}
    </div>
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="$emit('update:visible', false)">取消</el-button>
        <el-button type="primary" @click="handleTest" :loading="isTesting">测试连接</el-button>
        <el-button type="success" @click="handleSave">保存</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, defineProps, defineEmits } from 'vue';
import { useActorLocalizerStore } from '@/stores/actorLocalizer';

const props = defineProps({
  visible: Boolean,
  config: Object,
});

const emit = defineEmits(['update:visible', 'save']);

const actorStore = useActorLocalizerStore();
const localConfig = ref({});
const isTesting = ref(false);
const testResult = ref(null);

const defaultModels = {
    "Qwen/Qwen2-7B-Instruct": "（推荐，免费）",
    "THUDM/glm-4-9b-chat": "（推荐，免费）",
    "internlm/internlm2_5-7b-chat": "（免费）",
    "Qwen/Qwen2.5-72B-Instruct": "（性能强，收费）",
    "Qwen/Qwen2.5-32B-Instruct": "（性能强，收费）",
    "Qwen/Qwen2.5-14B-Instruct": "（收费）",
    "Qwen/Qwen2.5-7B-Instruct": "（免费）",
    "deepseek-ai/DeepSeek-V2.5": "（收费）",
};

watch(() => props.visible, (newVal) => {
  if (newVal) {
    localConfig.value = { ...props.config };
    testResult.value = null;
  }
});

const handleTest = async () => {
  isTesting.value = true;
  testResult.value = null;
  const result = await actorStore.testTranslationApi({
    mode: 'siliconflow',
    config: localConfig.value,
  });
  testResult.value = result;
  isTesting.value = false;
};

const handleSave = () => {
  emit('save', localConfig.value);
  emit('update:visible', false);
};
</script>

<style scoped>
.test-result {
  margin-top: 15px;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 14px;
}
.test-result.success {
  background-color: #f0f9eb;
  color: #67c23a;
  border: 1px solid #e1f3d8;
}
.test-result.error {
  background-color: #fef0f0;
  color: #f56c6c;
  border: 1px solid #fde2e2;
}
</style>