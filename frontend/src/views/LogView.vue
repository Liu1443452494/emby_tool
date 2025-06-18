// frontend/src/views/LogView.vue (新文件)
<template>
  <div class="log-page">
    <div class="page-header">
      <h2>应用日志</h2>
      <p>这里会实时显示应用后端的运行日志，最新的日志会显示在最上方。</p>
    </div>

    <div class="log-toolbar">
      <div class="pagination-controls">
        <el-button 
          @click="changePage(logStore.currentPage - 1)" 
          :disabled="logStore.currentPage <= 1"
        >
          上一页
        </el-button>
        <span>第 {{ logStore.currentPage }} / {{ logStore.totalPages }} 页 (共 {{ logStore.totalLogs }} 条)</span>
        <el-button 
          @click="changePage(logStore.currentPage + 1)" 
          :disabled="logStore.currentPage >= logStore.totalPages"
        >
          下一页
        </el-button>
      </div>
      <el-button type="danger" @click="logStore.clearLogs">清空日志</el-button>
    </div>

    <div class="log-container">
      <pre v-if="logStore.logs.length > 0" class="log-content">
        <div v-for="(log, index) in logStore.logs" :key="index" class="log-line">{{ log }}</div>
      </pre>
      <el-empty v-else description="暂无日志" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue';
import { useLogStore } from '@/stores/log';

const logStore = useLogStore();

onMounted(() => {
  logStore.fetchHistoricalLogs(1); // 加载第一页
  logStore.connect(); // 建立 WebSocket 连接
});

onUnmounted(() => {
  logStore.disconnect(); // 离开页面时断开连接
});

const changePage = (page) => {
  if (page > 0 && page <= logStore.totalPages) {
    logStore.fetchHistoricalLogs(page);
  }
};
</script>

<style scoped>
.log-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 0 20px;
}

.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.log-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 0;
  flex-shrink: 0;
}

.pagination-controls {
  display: flex;
  align-items: center;
  gap: 15px;
}

.log-container {
  flex-grow: 1;
  background-color: #1e1e1e;
  border-radius: 8px;
  padding: 15px;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
}

.log-content {
  margin: 0;
  font-family: 'Courier New', Courier, monospace;
  font-size: 14px;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-line {
  line-height: 1.6;
}
</style>