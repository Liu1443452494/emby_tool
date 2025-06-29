<!-- frontend/src/views/LogView.vue (修改后) -->
<template>
  <div class="log-page">
    <div class="page-header">
      <h2>应用日志</h2>
      <p>实时显示应用后端的运行日志，可按级别筛选，最新的日志会显示在最上方。</p>
    </div>

    <!-- 工具栏 -->
    <div class="log-toolbar">
      <div class="left-controls">
        <el-radio-group v-model="logLevelProxy" @change="handleLevelChange">
          <el-radio-button label="INFO">重要</el-radio-button>
          <el-radio-button label="DEBUG">调试</el-radio-button>
          <el-radio-button label="WARNING">警告</el-radio-button>
          <el-radio-button label="ERROR">错误</el-radio-button>
          <el-radio-button label="ALL">全部</el-radio-button>
        </el-radio-group>
      </div>
      <div class="right-controls">
        <el-button type="danger" @click="logStore.clearLogs" :disabled="logStore.totalLogs === 0">清空日志</el-button>
      </div>
    </div>

    <div class="log-container">
      <div v-if="logStore.logs.length > 0" class="log-content">
        <div v-for="(log, index) in logStore.logs" :key="index" class="log-line">
          <span class="line-number">{{ getLineNumber(index) }}</span>
          <span :class="['log-level', `log-level-${log.level.toLowerCase()}`]">{{ log.level }}:</span>
          <span class="log-timestamp">{{ log.timestamp }}</span>
          <span class="log-separator">-</span>
          <span class="log-category">{{ log.category }}</span>
          <span class="log-arrow">→</span>
          <span class="log-message">{{ log.message }}</span>
        </div>
      </div>
      <el-empty v-else description="暂无日志" />
    </div>

    <!-- 分页器 -->
    <div class="pagination-footer">
       <el-pagination
        v-model:current-page="logStore.currentPage"
        :page-size="100"
        :total="logStore.totalLogs"
        layout="total, prev, pager, next, jumper"
        background
        @current-change="handlePageChange"
        :disabled="logStore.totalLogs === 0"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, computed } from 'vue';
import { useLogStore } from '@/stores/log';

const logStore = useLogStore();

const logLevelProxy = computed({
  get: () => logStore.logLevel,
  set: (val) => {} // 只读代理
});

onMounted(() => {
  logStore.fetchHistoricalLogs(1);
  logStore.connect();
});

onUnmounted(() => {
  logStore.disconnect();
});

const handlePageChange = (page) => {
  logStore.fetchHistoricalLogs(page);
};

const handleLevelChange = (newLevel) => {
  logStore.setLogLevelAndFetch(newLevel);
};

const getLineNumber = (index) => {
  return logStore.totalLogs - ((logStore.currentPage - 1) * 100) - index;
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

.log-container {
  flex-grow: 1;
  background-color: #292A2D; 
  border-radius: 8px;
  padding: 10px 0;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
}

.log-content {
  /* 使用等宽字体是实现对齐的关键 */
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace;
  font-size: 14px;
  color: #bdc1c6;
}

.log-line {
  display: flex;
  align-items: baseline;
  line-height: 1.6;
  padding: 2px 10px;
  white-space: pre; /* 保证空格被保留，对于对齐至关重要 */
}
.log-line:hover {
  background-color: rgba(255, 255, 255, 0.05);
}

.line-number {
  width: 50px;
  text-align: right;
  color: #7f8389;
  user-select: none;
  margin-right: 15px;
  flex-shrink: 0;
}

.log-level {
  font-weight: bold;
  width: 80px; /* 固定宽度以对齐 */
  flex-shrink: 0;
}

.log-timestamp {
  color: #969ba1;
  flex-shrink: 0;
}

.log-separator {
  margin: 0 10px;
  color: #7f8389;
  flex-shrink: 0;
}

.log-category {
  width: 140px; /* 固定宽度以对齐 */
  color: #8ab4f8; /* 任务类别颜色 */
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-arrow {
  margin: 0 10px;
  color: #7f8389;
  flex-shrink: 0;
}

.log-message {
  flex-grow: 1;
  white-space: pre-wrap; 
  word-break: break-all;
}

.log-level-info { color: #67c23a; }
.log-level-warning { color: #e6a23c; }
.log-level-error { color: #f56c6c; }
.log-level-critical { color: #f56c6c; }
.log-level-debug { color: #909399; }

.pagination-footer {
  display: flex;
  justify-content: center;
  padding: 15px 0;
  flex-shrink: 0;
}

.log-page :deep(.el-pagination.is-background .el-pager li.is-active) {
  background-color: #609e95;
}
.log-page :deep(.el-radio-button__inner) {
  border-radius: 0;
}
.log-page :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-top-left-radius: 4px;
  border-bottom-left-radius: 4px;
}
.log-page :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-top-right-radius: 4px;
  border-bottom-right-radius: 4px;
}
.log-page :deep(.el-radio-button__original-radio:checked+.el-radio-button__inner) {
  background-color: #609e95;
  border-color: #609e95;
  box-shadow: -1px 0 0 0 #609e95;
}
</style>