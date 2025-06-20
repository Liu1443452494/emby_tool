// frontend/src/components/SiliconflowApiConfigDialog.vue (修改后)
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
        <!-- 核心修改 1: 监听 @change 事件 -->
        <el-select 
          v-model="localConfig.model_name" 
          placeholder="请选择或输入模型名称" 
          style="width: 100%;" 
          filterable 
          allow-create
          @change="handleModelChange"
        >
          <el-option v-for="(remark, name) in localConfig.model_remarks" :key="name" :label="`${name} ${remark}`" :value="name" />
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
// 核心修改 2: 导入 ElMessageBox
import { ElMessageBox } from 'element-plus';

const props = defineProps({
  visible: Boolean,
  config: Object,
});

const emit = defineEmits(['update:visible', 'save']);

const actorStore = useActorLocalizerStore();
const localConfig = ref({});
const isTesting = ref(false);
const testResult = ref(null);

watch(() => props.visible, (newVal) => {
  if (newVal) {
    localConfig.value = JSON.parse(JSON.stringify(props.config));
    if (!localConfig.value.model_remarks) {
      localConfig.value.model_remarks = {};
    }
    testResult.value = null;
  }
});

// 核心修改 3: 新增 handleModelChange 方法
const handleModelChange = async (newModelName) => {
  if (newModelName && !localConfig.value.model_remarks.hasOwnProperty(newModelName)) {
    // 这是一个新创建的模型
    try {
      const { value } = await ElMessageBox.prompt(
        `您创建了一个新的模型 "${newModelName}"，请输入该模型的备注信息（例如：免费、推荐、收费等），留空则无备注。`,
        '添加模型备注',
        {
          confirmButtonText: '确认',
          cancelButtonText: '取消',
          inputPlaceholder: '请输入备注',
          // 允许输入为空
          inputValidator: (val) => { return true; },
        }
      );
      // 用户点击了确认，将新模型和备注添加到 model_remarks
      localConfig.value.model_remarks[newModelName] = value || ''; // 如果用户没输入，则备注为空字符串
    } catch (action) {
      // 用户点击了取消或关闭对话框
      // 将 model_name 重置为之前的值，防止新创建的未确认项被选中
      localConfig.value.model_name = props.config.model_name || '';
    }
  }
};

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
  // 核心修改 4: 保存逻辑简化，因为添加新模型的逻辑已经移到 handleModelChange 中
  // 不再需要在这里检查和添加模型
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