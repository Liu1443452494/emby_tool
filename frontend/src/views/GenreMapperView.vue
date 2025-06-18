// frontend/src/views/GenreMapperView.vue (修改后)
<template>
  <div class="page-container genre-mapper-page">
    <div class="page-layout">
      <!-- 左侧控制区 -->
      <div class="controls-panel">
        <h2 class="panel-title">类型替换</h2>

        <div class="control-section">
          <h3>1. 获取与保存</h3>
          <div class="button-grid">
            <el-button type="primary" @click="genreStore.fetchServerGenres" :loading="genreStore.isTableLoading">
              从服务器获取/刷新类型
            </el-button>
            <el-button @click="openEditor">
              编辑标准映射表
            </el-button>
          </div>
        </div>

        <div class="divider"></div>

        <div class="control-section">
          <h3>2. 执行目标</h3>
          <el-form label-position="top" class="control-form">
            <el-radio-group v-model="targetMode">
              <el-radio value="byType">按媒体类型</el-radio>
              <el-radio value="byLibrary">按媒体库</el-radio>
              <el-radio value="all">所有媒体库</el-radio>
            </el-radio-group>
            <div v-if="targetMode === 'byType'" class="sub-options">
              <el-radio-group v-model="targetMediaType">
                <el-radio value="Movie">仅电影</el-radio>
                <el-radio value="Series">仅电视剧</el-radio>
              </el-radio-group>
            </div>
            <div v-if="targetMode === 'byLibrary'" class="sub-options">
              <el-select v-model="selectedLibraryIds" multiple placeholder="请选择媒体库" style="width: 100%;" filterable>
                <el-option v-for="item in mediaStore.libraries" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </div>
            <div v-if="targetMode === 'all'" class="sub-options">
              <el-input 
                v-model="libraryBlacklist" 
                type="textarea"
                :rows="2"
                placeholder="输入要排除的媒体库名称，用英文逗号(,)隔开"
              />
            </div>
          </el-form>
        </div>

        <div class="divider"></div>

        <div class="control-section">
          <h3>3. 执行操作</h3>
          <div class="button-grid">
            <el-button 
              v-if="!genreStore.activePreviewTaskId"
              @click="handlePreview" 
              :loading="genreStore.isPreviewLoading" 
              :disabled="!!genreStore.activeApplyTaskId"
            >
              预览修改
            </el-button>
            <el-button 
              v-else
              type="warning"
              @click="handleStopPreview"
            >
              停止扫描
            </el-button>
            <el-button type="danger" @click="handleApply" :disabled="!canApply">
              应用修改
            </el-button>
          </div>
        </div>
      </div>

      <!-- 右侧展示区 -->
      <div class="results-panel">
        <div class="table-section">
          <h3 class="result-title">类型映射表</h3>
          <div v-if="genreStore.isTableLoading" class="table-skeleton-wrapper">
            <el-skeleton :rows="10" animated />
          </div>
          <el-table v-else :data="genreStore.tableData" height="100%" stripe empty-text="请点击左侧“获取/刷新类型”按钮">
            <el-table-column prop="original" label="原始类型" />
            <el-table-column label="替换为">
              <template #default="scope">
                <el-input v-model="genreStore.mapping[scope.row.original]" @change="handleMappingChange" placeholder="留空则不替换" />
              </template>
            </el-table-column>
            <el-table-column prop="id" label="类型 ID" width="150" />
          </el-table>
        </div>
        <div class="console-section">
          <h3 class="result-title">控制台日志</h3>
          <div class="console-output">
            <pre>{{ genreStore.consoleOutput || '预览结果将显示在这里...' }}</pre>
          </div>
        </div>
      </div>
    </div>

    <!-- 表格化编辑器对话框 -->
    <el-dialog v-model="isEditorVisible" title="编辑标准类型映射表" width="700px">
      <div class="editor-toolbar">
        <el-button @click="addMappingRow" type="primary" :icon="Plus">添加映射</el-button>
      </div>
      <el-table :data="editorTableData" height="400px" border>
        <el-table-column label="原始类型 (Key)">
          <template #default="scope">
            <el-input v-model="scope.row.key" placeholder="例如：Action" />
          </template>
        </el-table-column>
        <el-table-column label="替换值 (Value)">
          <template #default="scope">
            <el-input v-model="scope.row.value" placeholder="例如：动作" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="scope">
            <el-button @click="deleteMappingRow(scope.$index)" type="danger" :icon="Delete" circle />
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isEditorVisible = false">取消</el-button>
          <el-button type="success" @click="saveFromEditor">
            保存到配置文件
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed, onUnmounted } from 'vue'
import { useGenreStore } from '@/stores/genre'
import { useMediaStore } from '@/stores/media'
import { useTaskStore } from '@/stores/task'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useStorage } from '@vueuse/core'
import { Plus, Delete } from '@element-plus/icons-vue'

const genreStore = useGenreStore()
const mediaStore = useMediaStore()
const taskStore = useTaskStore()

const targetMode = useStorage('genre-targetMode', 'byType')
const targetMediaType = useStorage('genre-targetMediaType', 'Movie')
const selectedLibraryIds = useStorage('genre-selectedLibraryIds', [])
const libraryBlacklist = useStorage('genre-libraryBlacklist', '')

const canApply = computed(() => genreStore.previewResults && genreStore.previewResults.length > 0 && !genreStore.activeApplyTaskId && !genreStore.activePreviewTaskId)

const isEditorVisible = ref(false)
const editorTableData = ref([])

onMounted(() => {
  mediaStore.fetchLibraries()
  genreStore.fetchStandardMapping()
  taskStore.connect()
})

onUnmounted(() => {
  genreStore.isPreviewLoading = false;
})

const handleMappingChange = () => {
  genreStore.previewResults = []
  genreStore.consoleOutput = '操作映射已更改，请重新运行预览。'
}

const handlePreview = () => {
  if (!genreStore.tableData || genreStore.tableData.length === 0) {
    ElMessage.warning('请先点击“从服务器获取/刷新类型”按钮来加载类型列表。')
    return
  }
  const isActionable = Object.entries(genreStore.mapping).some(([key, value]) => {
    return value && String(value).trim() !== '' && String(value).trim() !== String(key).trim();
  });
  if (!isActionable) {
    ElMessage.info('映射表中没有任何需要执行的替换操作，无需预览。')
    return
  }
  if (targetMode.value === 'byLibrary' && (!selectedLibraryIds.value || selectedLibraryIds.value.length === 0)) {
    ElMessage.warning('在“按媒体库”模式下，请至少选择一个媒体库。')
    return
  }
  const request = {
    mode: targetMode.value,
    media_type: targetMode.value === 'byType' ? targetMediaType.value : null,
    library_ids: targetMode.value === 'byLibrary' ? selectedLibraryIds.value : [],
    blacklist: targetMode.value === 'all' ? libraryBlacklist.value : ''
  }
  genreStore.startPreview(request)
}

const handleStopPreview = async () => {
  if (genreStore.activePreviewTaskId) {
    await taskStore.cancelTask(genreStore.activePreviewTaskId);
  }
}

const handleApply = async () => {
  try {
    await ElMessageBox.confirm(
      `即将对 ${genreStore.previewResults.length} 个媒体项应用类型修改。此操作不可逆，是否继续？`,
      '确认操作',
      { confirmButtonText: '确定应用', cancelButtonText: '取消', type: 'warning' }
    )
    genreStore.startApply()
  } catch (error) { /* 用户点击取消 */ }
}

const openEditor = async () => {
  await genreStore.fetchStandardMapping()
  editorTableData.value = Object.entries(genreStore.standardMapping).map(([key, value]) => ({ key, value }))
  isEditorVisible.value = true
}

const addMappingRow = () => {
  editorTableData.value.push({ key: '', value: '' })
}

const deleteMappingRow = (index) => {
  editorTableData.value.splice(index, 1)
}

const saveFromEditor = async () => {
  const newMapping = {}
  for (const row of editorTableData.value) {
    const key = row.key.trim()
    const value = row.value.trim()
    if (key) { newMapping[key] = value }
  }
  await genreStore.saveStandardMapping(newMapping)
  isEditorVisible.value = false
}

watch(() => taskStore.tasks, (newTasks, oldTasks) => {
  const activePreviewId = genreStore.activePreviewTaskId;
  const activeApplyId = genreStore.activeApplyTaskId;

  if (activePreviewId && !newTasks.some(t => t.id === activePreviewId)) {
    const finishedTask = oldTasks.find(t => t.id === activePreviewId);
    
    if (finishedTask) {
      if (finishedTask.status === 'completed' && finishedTask.result) {
        const result = finishedTask.result;
        genreStore.previewResults = result.results;
        genreStore.consoleOutput = result.logs;
        ElMessage.success('预览任务完成！');
      } else if (finishedTask.status === 'failed') {
        ElMessage.error('预览任务失败，请检查应用日志。');
        genreStore.consoleOutput = '预览任务执行失败。';
      } else {
        genreStore.consoleOutput = '预览任务已停止。';
      }
    }
    
    genreStore.isPreviewLoading = false;
    genreStore.clearActivePreviewTask();
  }

  if (activeApplyId && !newTasks.some(t => t.id === activeApplyId)) {
    const finishedTask = oldTasks.find(t => t.id === activeApplyId);

    if (finishedTask && finishedTask.status === 'completed') {
      ElMessage.success('应用修改成功！');
    } else if (finishedTask && finishedTask.status === 'failed') {
      ElMessage.error('应用修改失败，请检查应用日志。');
    } else {
      ElMessage.warning('应用修改任务已停止。');
    }

    genreStore.isPreviewLoading = false;
    genreStore.clearActiveApplyTask();
    genreStore.previewResults = [];
    genreStore.consoleOutput = '应用修改任务已完成。\n\n如需继续操作，请重新预览。';
  }
}, { deep: true });
</script>

<!-- 核心修改: 添加 scoped style -->
<style scoped>
.genre-mapper-page {
  --custom-theme-color: #609e95;
  --custom-theme-color-hover: #7fb8af;
  --custom-theme-color-active: #4a8a7f;
  height: 100%;
  overflow: hidden;
}
.page-layout { display: flex; height: 100%; }
.controls-panel {
  width: 380px;
  flex-shrink: 0;
  padding: 20px;
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
}
.panel-title { margin: 0 0 10px 0; font-size: 1.8rem; }
.control-section h3 { margin: 0 0 15px 0; font-size: 1.1rem; }
.control-form { display: flex; flex-direction: column; gap: 15px; }
.divider { border-top: 1px solid var(--el-border-color-lighter); margin: 10px 0; }
.sub-options { padding: 10px 0; }
.results-panel {
  flex-grow: 1;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow: hidden;
}
.table-section {
  flex: 3;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.table-skeleton-wrapper {
  padding: 10px;
  height: 100%;
  box-sizing: border-box;
}
.console-section {
  flex: 2;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.result-title {
  margin: 0 0 15px 0;
  font-size: 1.2rem;
  font-weight: bold;
}
.console-output {
  flex-grow: 1;
  background-color: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Courier New', Courier, monospace;
  font-size: 14px;
  border-radius: 4px;
  padding: 15px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-darker);
}
.console-output pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.editor-toolbar {
  margin-bottom: 15px;
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

/* --- 主题色样式 --- */
.genre-mapper-page :deep(.el-button--primary),
.genre-mapper-page :deep(.el-button--success) {
  --el-button-bg-color: var(--custom-theme-color);
  --el-button-border-color: var(--custom-theme-color);
  --el-button-hover-bg-color: var(--custom-theme-color-hover);
  --el-button-hover-border-color: var(--custom-theme-color-hover);
  --el-button-active-bg-color: var(--custom-theme-color-active);
  --el-button-active-border-color: var(--custom-theme-color-active);
}
.genre-mapper-page :deep(.el-radio__input.is-checked .el-radio__inner) {
  border-color: var(--custom-theme-color);
  background: var(--custom-theme-color);
}
.genre-mapper-page :deep(.el-radio__input.is-checked+.el-radio__label) {
  color: var(--custom-theme-color);
}
.genre-mapper-page :deep(.el-select .el-tag) {
  --el-tag-bg-color: color-mix(in srgb, var(--custom-theme-color) 20%, transparent);
  --el-tag-border-color: color-mix(in srgb, var(--custom-theme-color) 30%, transparent);
  --el-tag-text-color: var(--custom-theme-color);
}
.genre-mapper-page :deep(.el-select .el-tag .el-tag__close) {
  color: var(--custom-theme-color);
}
.genre-mapper-page :deep(.el-select .el-tag .el-tag__close:hover) {
  background-color: var(--custom-theme-color);
  color: white;
}
</style>