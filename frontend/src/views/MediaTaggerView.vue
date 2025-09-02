<!-- frontend/src/views/MediaTaggerView.vue (完整文件覆盖) -->
<template>
  <div class="media-tagger-page">
    <div class="page-header">
      <h2>媒体标签器</h2>
      <p>创建自定义规则，为符合条件的媒体自动添加或移除标签。</p>
    </div>

    <div class="toolbar">
      <el-button type="primary" :icon="Plus" @click="openRuleDialog()">添加规则</el-button>
      <el-button type="success" @click="handleRunTagger" :loading="isApplying">立即应用所有规则</el-button>
      <el-button @click="isClearDialogVisible = true" :icon="Delete" style="margin-left: 10px;">
        清除标签...
      </el-button>
    </div>

    <el-table :data="taggerStore.config.rules" style="width: 100%" v-loading="taggerStore.isLoading" border>
      <el-table-column label="启用" width="70" align="center">
        <template #default="scope">
          <el-switch v-model="scope.row.enabled" @change="handleRuleToggle(scope.row)" />
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="规则备注" min-width="200" />
      <el-table-column label="目标媒体库" min-width="180">
        <template #default="scope">
          {{ formatTargetLibraries(scope.row.target.libraries) }}
        </template>
      </el-table-column>
      <el-table-column label="类型筛选" min-width="200">
        <template #default="scope">
          {{ formatTargetGenres(scope.row.target.genres) }}
        </template>
      </el-table-column>
      <el-table-column label="添加的标签" min-width="150">
        <template #default="scope">
          <el-tag v-for="tag in scope.row.action.add_tags" :key="tag" class="action-tag" type="success">{{ tag }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="移除的标签" min-width="150">
        <template #default="scope">
          <el-tag v-for="tag in scope.row.action.remove_tags" :key="tag" class="action-tag" type="danger">{{ tag }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="scope">
          <el-button type="primary" :icon="Edit" circle @click="openRuleDialog(scope.row, scope.$index)"></el-button>
          <el-button type="danger" :icon="Delete" circle @click="deleteRule(scope.$index)"></el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="config-section">
        <h3>定时任务</h3>
        <el-form label-position="left" label-width="120px">
            <el-form-item label="启用定时任务">
                <el-switch v-model="taggerStore.config.enabled" />
            </el-form-item>
            <el-form-item label="CRON 表达式">
                <el-input v-model="taggerStore.config.cron" placeholder="例如: 0 2 * * *" :disabled="!taggerStore.config.enabled" />
                <div class="form-item-description cron-preview" :class="{ 'is-error': !isCronValid }">
                    {{ cronDescription }}
                </div>
            </el-form-item>
            <el-form-item>
                <el-button type="success" @click="saveFullConfig" :loading="taggerStore.isLoading" :disabled="taggerStore.config.enabled && !isCronValid">保存定时任务设置</el-button>
            </el-form-item>
        </el-form>
    </div>

    <el-dialog v-model="isRuleDialogVisible" :title="isEditing ? '编辑规则' : '添加规则'" width="60%" top="5vh">
      <el-form :model="currentRule" label-position="top" ref="ruleFormRef">
        <el-form-item label="规则备注" prop="remark" :rules="{ required: true, message: '备注不能为空', trigger: 'blur' }">
          <el-input v-model="currentRule.remark" placeholder="例如：为所有科幻电影打上标签"></el-input>
        </el-form-item>
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="目标媒体库">
              <el-radio-group v-model="currentRule.target.libraries.mode">
                <el-radio-button value="all">所有媒体库</el-radio-button>
                <el-radio-button value="include">包含指定库</el-radio-button>
                <el-radio-button value="exclude">排除指定库</el-radio-button>
              </el-radio-group>
              <el-select v-if="currentRule.target.libraries.mode !== 'all'" v-model="currentRule.target.libraries.names" multiple filterable placeholder="请选择媒体库" style="width: 100%; margin-top: 10px;">
                <el-option v-for="lib in mediaStore.libraries" :key="lib.id" :label="lib.name" :value="lib.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="类型筛选">
              <el-radio-group v-model="currentRule.target.genres.mode">
                <el-radio-button value="any">不筛选</el-radio-button>
                <el-radio-button value="include">必须包含</el-radio-button>
                <el-radio-button value="exclude">必须排除</el-radio-button>
              </el-radio-group>
              <div v-if="currentRule.target.genres.mode !== 'any'" style="margin-top: 10px;">
                <el-radio-group v-model="currentRule.target.genres.match" size="small">
                    <el-radio-button value="or">满足任意一个 (OR)</el-radio-button>
                    <el-radio-button value="and">必须全部满足 (AND)</el-radio-button>
                </el-radio-group>
                <TagInput v-model="currentRule.target.genres.names" placeholder="输入类型后按回车" style="margin-top: 10px;" />
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-divider />
        <el-row :gutter="20">
            <el-col :span="12">
                <el-form-item label="添加标签">
                    <TagInput v-model="currentRule.action.add_tags" placeholder="输入要添加的标签后按回车" />
                </el-form-item>
            </el-col>
            <el-col :span="12">
                <el-form-item label="移除标签">
                    <TagInput v-model="currentRule.action.remove_tags" placeholder="输入要移除的标签后按回车" />
                </el-form-item>
            </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="isRuleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="isClearDialogVisible" title="清除媒体标签" width="500px">
        <el-form :model="clearScope" label-position="top">
            <el-form-item label="选择操作范围">
                <el-radio-group v-model="clearScope.mode">
                    <el-radio-button value="all">所有媒体库</el-radio-button>
                    <el-radio-button value="include">指定媒体库</el-radio-button>
                </el-radio-group>
                <el-select v-if="clearScope.mode === 'include'" v-model="clearScope.library_names" multiple filterable placeholder="请选择媒体库" style="width: 100%; margin-top: 10px;">
                    <el-option v-for="lib in mediaStore.libraries" :key="lib.id" :label="lib.name" :value="lib.name" />
                </el-select>
            </el-form-item>
            <el-form-item label="移除指定标签 (多个用英文逗号隔开)">
                <el-input v-model="tagsToRemoveInput" placeholder="例如: 待整理, 修复封面" />
            </el-form-item>
        </el-form>
        <template #footer>
            <div class="dialog-footer-actions">
                <el-button type="warning" @click="handleRemoveSpecificTags" :disabled="!tagsToRemoveInput.trim()">移除指定标签</el-button>
                <el-button type="danger" @click="handleClearAllTags">清空范围内所有标签</el-button>
            </div>
        </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue';
import { useMediaTaggerStore } from '@/stores/mediaTagger';
import { useMediaStore } from '@/stores/media';
import { Plus, Edit, Delete } from '@element-plus/icons-vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { useRouter } from 'vue-router';
import _ from 'lodash';
import { v4 as uuidv4 } from 'uuid';
import TagInput from '@/components/common/TagInput.vue';
import cronstrue from 'cronstrue/i18n';

const taggerStore = useMediaTaggerStore();
const mediaStore = useMediaStore();
const router = useRouter();

const isRuleDialogVisible = ref(false);
const isClearDialogVisible = ref(false);
const isEditing = ref(false);
const editingIndex = ref(-1);
const ruleFormRef = ref(null);
const isApplying = ref(false);

const clearScope = ref({
    mode: 'all',
    library_names: []
});
const tagsToRemoveInput = ref('');

const defaultRule = () => ({
  id: uuidv4(),
  enabled: true,
  remark: '',
  target: { libraries: { mode: 'all', names: [] }, genres: { mode: 'any', names: [], match: 'or' } },
  action: { add_tags: [], remove_tags: [] }
});

const currentRule = ref(defaultRule());

onMounted(() => {
  taggerStore.fetchConfig();
  mediaStore.fetchLibraries();
});

const isCronValid = ref(true);
const cronDescription = computed(() => {
  const cronValue = taggerStore.config.cron;
  if (!taggerStore.config.enabled || !cronValue) {
    isCronValid.value = true;
    return '定时任务已禁用或未设置表达式。';
  }
  try {
    const description = cronstrue.toString(cronValue, { locale: "zh_CN" });
    isCronValid.value = true;
    return `任务释义: ${description}`;
  } catch (e) {
    isCronValid.value = false;
    return `无效的CRON表达式: ${e}`;
  }
});

const formatTargetLibraries = (libraries) => {
  if (libraries.mode === 'all') return '所有媒体库';
  const modeText = libraries.mode === 'include' ? '包含' : '排除';
  const names = libraries.names.join(', ') || '未指定';
  return `${modeText}: ${names}`;
};

const formatTargetGenres = (genres) => {
  if (genres.mode === 'any') return '不筛选';
  const modeText = genres.mode === 'include' ? '包含' : '排除';
  const matchText = genres.match === 'or' ? '任意一个' : '全部';
  const names = genres.names.join(', ') || '未指定';
  return `${modeText} (${matchText}): ${names}`;
};

const openRuleDialog = (rule = null, index = -1) => {
  if (rule) {
    isEditing.value = true;
    editingIndex.value = index;
    currentRule.value = _.cloneDeep(rule);
  } else {
    isEditing.value = false;
    editingIndex.value = -1;
    currentRule.value = defaultRule();
  }
  isRuleDialogVisible.value = true;
};

const saveRule = async () => {
  await ruleFormRef.value.validate(async (valid) => {
    if (valid) {
      const newConfig = _.cloneDeep(taggerStore.config);
      if (isEditing.value) {
        newConfig.rules[editingIndex.value] = currentRule.value;
      } else {
        newConfig.rules.push(currentRule.value);
      }
      const success = await taggerStore.saveConfig(newConfig);
      if (success) isRuleDialogVisible.value = false;
    }
  });
};

const deleteRule = async (index) => {
    await ElMessageBox.confirm('确定要删除这条规则吗？', '警告', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning',
    });
    const newConfig = _.cloneDeep(taggerStore.config);
    newConfig.rules.splice(index, 1);
    await taggerStore.saveConfig(newConfig);
};

const handleRuleToggle = async () => {
    await taggerStore.saveConfig(taggerStore.config);
};

const saveFullConfig = async () => {
    if (taggerStore.config.enabled && !isCronValid.value) {
        ElMessage.error('无法保存，CRON 表达式无效！');
        return;
    }
    await taggerStore.saveConfig(taggerStore.config);
};

const handleRunTagger = async () => {
    isApplying.value = true;
    const success = await taggerStore.runTagger();
    if (success) router.push('/tasks');
    isApplying.value = false;
};

const handleClearAllTags = async () => {
  try {
    await ElMessageBox.confirm(
      `您确定要清空 ${clearScope.value.mode === 'all' ? '所有媒体库' : '指定媒体库'} 中所有媒体的所有标签吗？此操作不可恢复。`,
      '⚠️ 危险操作确认',
      { confirmButtonText: '我确定，全部清空', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' }
    );
    const success = await taggerStore.clearAllTags(clearScope.value);
    if (success) {
      isClearDialogVisible.value = false;
      router.push('/tasks');
    }
  } catch (error) {
    if (error !== 'cancel') ElMessage.info('操作已取消');
  }
};

const handleRemoveSpecificTags = async () => {
  const tags = tagsToRemoveInput.value.split(',').map(t => t.trim()).filter(Boolean);
  if (tags.length === 0) {
    ElMessage.warning('请输入要移除的标签');
    return;
  }
  try {
    await ElMessageBox.confirm(
      `您确定要从 ${clearScope.value.mode === 'all' ? '所有媒体库' : '指定媒体库'} 中移除标签 [${tags.join(', ')}] 吗？`,
      '操作确认',
      { confirmButtonText: '确定移除', cancelButtonText: '取消', type: 'warning' }
    );
    const success = await taggerStore.removeSpecificTags(tags, clearScope.value);
    if (success) {
      isClearDialogVisible.value = false;
      router.push('/tasks');
    }
  } catch (error) {
    if (error !== 'cancel') ElMessage.info('操作已取消');
  }
};
</script>

<style scoped>
.media-tagger-page { padding: 0 20px; }
.page-header { padding: 20px 0; border-bottom: 1px solid var(--el-border-color-light); }
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }
.toolbar { padding: 20px 0; }
.action-tag { margin-right: 5px; margin-bottom: 5px; }
.config-section { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--el-border-color-light); }
.config-section h3 { font-size: 1.1rem; margin-bottom: 20px; }
.dialog-footer-actions { display: flex; justify-content: space-between; width: 100%; }
.cron-preview {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.cron-preview.is-error {
  color: var(--el-color-danger);
}
</style>