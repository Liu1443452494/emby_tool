// frontend/stores/actorLocalizer.js (完整代码)
import { ref, watch } from 'vue'
import { defineStore, storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useTaskStore } from './task'
import { API_BASE_URL } from '@/config/apiConfig';

export const useActorLocalizerStore = defineStore('actorLocalizer', () => {
  const previewResults = ref([])
  const consoleOutput = ref('')
  const isLoading = ref(false)
  const activePreviewTaskId = ref(null)
  const activeApplyTaskId = ref(null)
  
  const searchResults = ref([])
  const isSearching = ref(false)

  const taskStore = useTaskStore();
  const { tasks } = storeToRefs(taskStore);

  watch(tasks, (newTasks) => {
    if (!activePreviewTaskId.value) return;

    const previewTask = newTasks.find(t => t.id === activePreviewTaskId.value);
    if (previewTask && previewTask.result) {
      previewResults.value = previewTask.result;
      
      const logLines = (previewTask.result || []).map(item => {
        const changes = Object.entries(item.changes).map(([name, ch]) => {
          let sourceText = '';
          if (ch.source === 'replace') sourceText = ' (来自暴力替换)';
          else if (ch.source === 'translation') sourceText = ' (来自翻译引擎)';
          else if (ch.source === 'douban') sourceText = ' (来自豆瓣)';
          return `  - ${name}: "${ch.old}" -> "${ch.new}"${sourceText}`;
        }).join('\n');
        return `[${item.name}]\n${changes}`;
      });
      
      let header = `正在扫描中... 已发现 ${logLines.length} 个可修改项。\n\n`;
      if (['completed', 'cancelled', 'failed'].includes(previewTask.status)) {
        header = `扫描完成！共发现 ${logLines.length} 个可修改项。\n\n`;
      }
      consoleOutput.value = header + logLines.join('\n\n');
    }
  }, { deep: true });


  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  function resetState() {
    isLoading.value = false
    activePreviewTaskId.value = null
    activeApplyTaskId.value = null
  }

  function clearResults() {
    previewResults.value = []
    consoleOutput.value = ''
    searchResults.value = []
  }

  async function searchMedia(query) {
    if (!query) {
      showMessage('warning', '请输入搜索内容！')
      return
    }
    isSearching.value = true
    searchResults.value = []
    try {
      const response = await fetch(`${API_BASE_URL}/api/media/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '搜索失败')
      if (data.length === 0) {
        showMessage('info', '未找到相关媒体。')
      }
      searchResults.value = data
    } catch (error) {
      showMessage('error', `搜索失败: ${error.message}`)
    } finally {
      isSearching.value = false
    }
  }

  async function startPreview(request) {
    clearResults();
    resetState();
    isLoading.value = true
    consoleOutput.value = '正在启动预览任务，请稍候...\n'
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-localizer/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '启动预览任务失败')
      
      activePreviewTaskId.value = data.task_id
      showMessage('success', data.message)
    } catch (error) {
      consoleOutput.value += `错误: ${error.message}\n`
      showMessage('error', error.message)
      isLoading.value = false
    }
  }

  async function startApply() {
    if (!previewResults.value || previewResults.value.length === 0) {
      showMessage('warning', '没有可应用的修改，请先运行预览。')
      return
    }
    isLoading.value = true
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-localizer/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: previewResults.value }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error('启动应用任务失败')
      
      activeApplyTaskId.value = data.task_id
      showMessage('success', data.message)
    } catch (error) {
      showMessage('error', error.message)
      isLoading.value = false;
    }
  }

  async function startDirectApply() {
    isLoading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-localizer/apply-directly`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || '启动任务失败');
      }
      activeApplyTaskId.value = data.task_id;
      showMessage('success', data.message);
    } catch (error) {
      showMessage('error', error.message);
      isLoading.value = false;
    }
  }

  async function testTranslationApi(payload) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/actor-localizer/test-translation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || '测试请求失败');
      }
      return { success: true, message: data.message };
    } catch (error) {
      return { success: false, message: error.message };
    }
  }

  function clearActivePreviewTask() {
    activePreviewTaskId.value = null
  }

  function clearActiveApplyTask() {
    activeApplyTaskId.value = null
  }

  return {
    previewResults,
    consoleOutput,
    isLoading,
    activePreviewTaskId,
    activeApplyTaskId,
    searchResults,
    isSearching,
    resetState,
    clearResults,
    searchMedia,
    startPreview,
    startApply,
    startDirectApply,
    testTranslationApi,
    clearActivePreviewTask,
    clearActiveApplyTask,
  }
})