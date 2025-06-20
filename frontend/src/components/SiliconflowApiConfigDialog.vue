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
        <el-select 
          v-model="localConfig.model_name" 
          placeholder="请选择或输入模型名称" 
          style="width: 100%;" 
          filterable 
          allow-create
          @change="handleModelChange"
        >
          <el-option v-for="(remark, name) in localConfig.model_remarks" :key="name" :label="`${name} ${remark}`" :value="name">
            <div class="option-with-delete">
              <span>{{ name }} <span class="option-remark">{{ remark }}</span></span>
              <el-button 
                type="danger" 
                :icon="Delete" 
                circle 
                text 
                class="delete-button"
                @click.stop="handleDeleteModel(name)"
              />
            </div>
          </el-option>
        </el-select>
      </el-form-item>

      <el-form-item>
        <template #label>
          <span>
            温度 (Temperature)
            <el-tooltip effect="dark" content="控制输出的随机性。值越低，输出越确定和重复；值越高，输出越随机和有创意。对于翻译任务，建议使用较低的值。" placement="top">
              <el-icon><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
        </template>
        <div class="slider-wrapper">
          <el-slider v-model="localConfig.temperature" :min="0.0" :max="2.0" :step="0.01" show-input />
        </div>
      </el-form-item>

      <el-form-item>
         <template #label>
          <span>
            核心采样 (Top P)
            <el-tooltip effect="dark" content="控制生成文本的多样性。它会从概率最高的词中进行采样，直到累积概率达到 Top P 的值。1.0 表示不进行筛选。通常建议只修改温度或核心采样中的一个。" placement="top">
              <el-icon><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
        </template>
        <div class="slider-wrapper">
          <el-slider v-model="localConfig.top_p" :min="0.0" :max="1.0" :step="0.01" show-input />
        </div>
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
import { ElMessageBox, ElMessage } from 'element-plus';
import { Delete, QuestionFilled } from '@element-plus/icons-vue';

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
    if (typeof localConfig.value.temperature === 'undefined') {
      localConfig.value.temperature = 0.0;
    }
    if (typeof localConfig.value.top_p === 'undefined') {
      localConfig.value.top_p = 1.0;
    }
    testResult.value = null;
  }
});

const handleModelChange = async (newModelName) => {
  if (newModelName && !localConfig.value.model_remarks.hasOwnProperty(newModelName)) {
    try {
      const { value } = await ElMessageBox.prompt(
        `您创建了一个新的模型 "${newModelName}"，请输入该模型的备注信息（例如：免费、推荐、收费等），留空则无备注。`,
        '添加模型备注',
        {
          confirmButtonText: '确认',
          cancelButtonText: '取消',
          inputPlaceholder: '请输入备注',
          inputValidator: (val) => { return true; },
        }
      );
      localConfig.value.model_remarks[newModelName] = value || '';
    } catch (action) {
      localConfig.value.model_name = props.config.model_name || '';
    }
  }
};

const handleDeleteModel = async (modelNameToDelete) => {
  try {
    await ElMessageBox.confirm(
      `确定要从配置中永久删除模型 “${modelNameToDelete}” 吗？此操作不可恢复。`,
      '警告',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    );
    
    delete localConfig.value.model_remarks[modelNameToDelete];

    if (localConfig.value.model_name === modelNameToDelete) {
      localConfig.value.model_name = '';
    }

    ElMessage.success(`模型 “${modelNameToDelete}” 已删除。`);

  } catch (error) {
    // 用户点击了取消
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
  emit('save', localConfig.value);
  emit('update:visible', false);
};
</script>

<style scoped>
.option-with-delete {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.option-remark {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 8px;
}

.delete-button {
  visibility: hidden;
  margin-left: 10px;
}

.el-select-dropdown__item:hover .delete-button {
  visibility: visible;
}

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

.el-form-item :deep(.el-form-item__label) {
  display: flex;
  align-items: center;
  gap: 5px;
}

.slider-wrapper {
  width: 100%;
}

/* --- 核心修改：调整 el-slider 附带的 input-number 宽度 --- */
.slider-wrapper :deep(.el-slider__input) {
  /* 将宽度从 100px 增加到 130px 或 140px，根据需要调整 */
  width: 140px; 
}
/* --- 结束修改 --- */
</style>