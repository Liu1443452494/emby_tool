// frontend/src/views/LogView.vue (修改后)
<template>
  <div class="log-page">
    <div class="page-header">
      <h2>应用日志</h2>
      <p>这里会实时显示应用后端的运行日志，最新的日志会显示在最上方。</p>
    </div>

    <div class="log-toolbar">
      <!-- 核心修改：使用 el-pagination 组件 -->
      <el-pagination
        v-model:current-page="logStore.currentPage"
        :page-size="100"
        :total="logStore.totalLogs"
        layout="total, prev, pager, next, jumper"
        background
        @current-change="handlePageChange"
        :disabled="logStore.totalLogs === 0"
      />
      <!-- 结束修改 -->
      <el-button type="danger" @click="logStore.clearLogs" :disabled="logStore.totalLogs === 0">清空日志</el-button>
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

// 核心修改：定义新的页码改变处理函数
const handlePageChange = (page) => {
  logStore.fetchHistoricalLogs(page);
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

/* 核心修改：移除旧的 pagination-controls 样式 */

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

/* 核心修改：为 el-pagination 添加主题色 */
.log-page :deep(.el-pagination.is-background .el-pager li.is-active) {
  background-color: #609e95;
}
</style>