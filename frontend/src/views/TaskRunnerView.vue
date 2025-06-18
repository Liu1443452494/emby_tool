// frontend/src/views/TaskRunnerView.vue (修改后)
<template>
  <div class="task-page">
    <div class="page-header">
      <h2>运行任务</h2>
      <p>这里会实时显示正在后台运行的长耗时任务，您可以监控其状态或取消任务。</p>
    </div>

    <el-table :data="taskStore.tasks" style="width: 100%" empty-text="当前没有正在运行的任务">
      <el-table-column prop="name" label="任务名称" min-width="250" />
      
      <el-table-column label="进度" min-width="200">
        <template #default="scope">
          <!-- 核心修改 1: 增加 v-if 判断 total 是否为 -1 -->
          <div v-if="scope.row.total === -1" class="progress-indeterminate">
            <el-progress 
              :percentage="100" 
              :stroke-width="10"
              :show-text="false"
              striped
              striped-flow
            />
            <span class="progress-text">已处理 {{ scope.row.progress }} 项</span>
          </div>
          <div v-else class="progress-determinate">
            <el-progress 
              :percentage="calculatePercentage(scope.row.progress, scope.row.total)" 
              :stroke-width="10"
              striped
              striped-flow
              :status="getProgressStatus(scope.row.status)"
            />
            <span class="progress-text">{{ scope.row.progress }} / {{ scope.row.total }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column prop="start_time" label="开始时间" width="200">
        <template #default="scope">
          {{ formatTime(scope.row.start_time) }}
        </template>
      </el-table-column>

      <el-table-column prop="status" label="状态" width="120">
        <template #default="scope">
          <el-tag :type="getStatusType(scope.row.status)">
            {{ getStatusText(scope.row.status) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="120" fixed="right">
        <template #default="scope">
          <el-button
            type="danger"
            size="small"
            @click="taskStore.cancelTask(scope.row.id)"
            :disabled="scope.row.status !== 'running'"
          >
            取消任务
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue';
import { useTaskStore } from '@/stores/task';

const taskStore = useTaskStore();

onMounted(() => {
  taskStore.connect();
});

onUnmounted(() => {
  taskStore.disconnect();
});

// 核心修改 2: 调整百分比计算，避免除以 -1
const calculatePercentage = (progress, total) => {
  if (total <= 0) return 0; // 如果 total 是 0 或负数，都返回 0
  return Math.round((progress / total) * 100);
};

const formatTime = (isoString) => {
  if (!isoString) return '-';
  return new Date(isoString).toLocaleString();
};

const getStatusType = (status) => {
  switch (status) {
    case 'running': return 'primary';
    case 'cancelling': return 'warning';
    case 'completed': return 'success';
    case 'failed': return 'danger';
    case 'cancelled': return 'info';
    default: return 'info';
  }
};

const getStatusText = (status) => {
  const map = {
    running: '运行中',
    cancelling: '取消中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };
  return map[status] || '未知';
};

const getProgressStatus = (status) => {
  if (status === 'failed') return 'exception';
  if (status === 'completed') return 'success';
  return '';
}
</script>

<style scoped>
.task-page {
  padding: 0 20px;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  margin-bottom: 20px;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.progress-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: 8px;
  white-space: nowrap; /* 防止文字换行 */
}

/* 核心修改 3: 确保两种模式下布局一致 */
.progress-indeterminate, .progress-determinate {
  display: flex;
  align-items: center;
  width: 100%;
}

:deep(.el-progress) {
  width: 100%;
  flex-grow: 1;
}
</style>