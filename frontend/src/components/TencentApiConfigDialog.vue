// frontend/src/components/TencentApiConfigDialog.vue (新文件)
<template>
  <el-dialog
    :model-value="visible"
    title="腾讯云翻译API配置"
    width="500px"
    @update:model-value="$emit('update:visible', $event)"
    :close-on-click-modal="false"
  >
    <el-form :model="localConfig" label-position="top">
      <el-form-item label="SecretId">
        <el-input v-model="localConfig.secret_id" placeholder="请输入腾讯云 SecretId" />
      </el-form-item>
      <el-form-item label="SecretKey">
        <el-input v-model="localConfig.secret_key" placeholder="请输入腾讯云 SecretKey" show-password />
      </el-form-item>
      <el-form-item label="地域 (Region)">
        <el-select v-model="localConfig.region" placeholder="请选择地域" style="width: 100%;">
          <el-option v-for="region in regions" :key="region" :label="region" :value="region" />
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

const regions = [
  "ap-guangzhou", "ap-shanghai", "ap-nanjing", "ap-beijing", 
  "ap-chengdu", "ap-chongqing", "ap-hongkong", "ap-singapore", 
  "ap-mumbai", "na-ashburn", "na-toronto", "eu-frankfurt"
];

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
    mode: 'tencent',
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