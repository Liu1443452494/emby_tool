// frontend/src/stores/task.js (修改后)
import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { useActorLocalizerStore } from './actorLocalizer'
import { useGenreStore } from './genre'
import { useMediaStore } from './media'
import { useDoubanStore } from './douban'
import { useConfigStore } from './config'
// --- 核心修改 1: 导入 API 配置 ---
import { API_BASE_URL, WS_BASE_URL } from '@/config/apiConfig';


export const useTaskStore = defineStore('task', () => {
  const tasks = ref([])
  const isConnected = ref(false)
  let ws = null
  let reconnectTimer = null

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    // --- 核心修改 2: 使用导入的常量，并拼接路径 ---
    ws = new WebSocket(`${WS_BASE_URL}/ws/tasks`)
    ws.onopen = () => {
      isConnected.value = true
      console.log("任务 WebSocket 已连接")
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    }
    ws.onmessage = (event) => { tasks.value = JSON.parse(event.data) }
    ws.onclose = () => {
      isConnected.value = false
      console.log("任务 WebSocket 已断开")
      if (!reconnectTimer) { reconnectTimer = setTimeout(() => connect(), 5000) }
    }
    ws.onerror = (error) => { isConnected.value = false; console.error("任务 WebSocket 错误:", error) }
  }

  function disconnect() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (ws) { ws.onclose = null; ws.close(); ws = null; isConnected.value = false; console.log("任务 WebSocket 已手动断开") }
  }

  async function cancelTask(taskId) {
    try {
      // --- 核心修改 3: 使用导入的常量，并拼接路径 ---
      const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}/cancel`, {
        method: 'POST'
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '发送取消请求失败')
      
      showMessage('warning', data.message)
    } catch (error) {
      showMessage('error', `取消任务失败: ${error.message}`)
    }
  }

  watch(tasks, (newTasks, oldTasks) => {
    if (!oldTasks) return;

    newTasks.forEach(newTask => {
      const oldTask = oldTasks.find(t => t.id === newTask.id);
      
      const isFinalState = ['completed', 'failed', 'cancelled'].includes(newTask.status);
      const wasNotFinalState = !oldTask || !['completed', 'failed', 'cancelled'].includes(oldTask.status);

      if (isFinalState && wasNotFinalState) {
        const finishedTask = newTask;
        
        if (finishedTask.name.includes('演员中文化')) {
          const actorStore = useActorLocalizerStore();
          const isPreview = finishedTask.name.includes('预览');
          
          if (isPreview) {
            // --- BUG 修复：在这里处理最终结果，避免竞态条件 ---
            if (finishedTask.status === 'completed' && finishedTask.result) {
                actorStore.previewResults = finishedTask.result;
                // 同时更新最终的控制台日志
                const logLines = (finishedTask.result || []).map(item => {
                    const changes = Object.entries(item.changes).map(([name, ch]) => {
                        let sourceText = '';
                        if (ch.source === 'replace') sourceText = ' (来自暴力替换)';
                        else if (ch.source === 'translation') sourceText = ' (来自翻译引擎)';
                        else if (ch.source === 'douban') sourceText = ' (来自豆瓣)';
                        return `  - ${name}: "${ch.old}" -> "${ch.new}"${sourceText}`;
                    }).join('\n');
                    return `[${item.name}]\n${changes}`;
                });
                actorStore.consoleOutput = `扫描完成！共发现 ${logLines.length} 个可修改项。\n\n` + logLines.join('\n\n');
            }
            // --- 修复结束 ---

            if (finishedTask.status === 'completed') {
              showMessage('success', '演员中文化预览完成！');
            } else if (finishedTask.status === 'failed') {
              showMessage('error', '演员中文化预览失败');
            } else { // cancelled
              showMessage('warning', '演员中文化预览已取消');
            }
            
            actorStore.clearActivePreviewTask();
          } else { // 应用任务
             if (finishedTask.status === 'completed') {
                showMessage('success', '演员中文化应用成功！');
             } else if (finishedTask.status === 'failed') {
                showMessage('error', '演员中文化应用失败');
             } else { // cancelled
                showMessage('warning', '演员中文化应用已取消');
             }
             actorStore.clearActiveApplyTask();
          }
          actorStore.isLoading = false;
        }

        else if (finishedTask.name.includes('类型替换')) {
          const genreStore = useGenreStore();
          const isPreview = finishedTask.name.includes('预览');

          if (isPreview) {
            if (finishedTask.status === 'completed' && finishedTask.result) {
               genreStore.previewResults = finishedTask.result.results || [];
               genreStore.consoleOutput = finishedTask.result.logs;
               showMessage('success', '类型替换预览完成！');
            } else if (finishedTask.status === 'failed') {
               showMessage('error', '类型替换预览失败');
               genreStore.consoleOutput = '预览任务执行失败。';
            } else { // cancelled
               showMessage('warning', '类型替换预览已取消');
               genreStore.consoleOutput = '预览任务已停止。';
            }
            genreStore.clearActivePreviewTask();
          } else { // apply
             if (finishedTask.status === 'completed') {
                showMessage('success', '类型替换应用成功！');
             } else if (finishedTask.status === 'failed') {
                showMessage('error', '类型替换应用失败');
             } else { // cancelled
                showMessage('warning', '类型替换应用已取消');
             }
             genreStore.previewResults = [];
             genreStore.consoleOutput += '\n\n应用任务已完成，请重新预览。';
             genreStore.clearActiveApplyTask();
          }
          genreStore.isPreviewLoading = false;
        }

        else if (finishedTask.name.includes('批量下载')) {
            const mediaStore = useMediaStore();
            if (finishedTask.status === 'completed') {
                showMessage('success', '批量下载任务已完成！');
            } else if (finishedTask.status === 'failed') {
                showMessage('error', '批量下载任务失败。');
            } else { // cancelled
                showMessage('warning', '批量下载任务已取消。');
            }
            mediaStore.clearActiveBatchTask();
        }

        else if (finishedTask.name.includes('豆瓣')) {
            const doubanStore = useDoubanStore();
            const configStore = useConfigStore();
            if (finishedTask.status === 'completed') {
                showMessage('success', '豆瓣数据扫描完成！');
            } else if (finishedTask.status === 'failed') {
                showMessage('error', '豆瓣数据扫描失败。');
            } else { // cancelled
                showMessage('warning', '豆瓣数据扫描已取消。');
            }
            setTimeout(() => {
              configStore.isLoaded = false; 
              configStore.fetchConfig();
            }, 500);
            doubanStore.isLoading = false;
        }
      }
    });
  }, { deep: true });

  return { tasks, isConnected, connect, disconnect, cancelTask }
})