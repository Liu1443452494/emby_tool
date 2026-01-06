<!-- frontend/src/views/TaskRunnerView.vue (完整文件覆盖 - Naive UI 重构版) -->
<template>
  <div class="task-page-naive">
    <div class="page-header">
      <h2>运行任务</h2>
      <p>这里会实时显示正在后台运行的长耗时任务，您可以监控其状态或取消任务。</p>
    </div>

    <n-data-table
      :columns="columns"
      :data="taskStore.tasks"
      :bordered="false"
      :single-line="false"
      class="task-table"
    >
      <template #empty>
        <n-empty description="当前没有正在运行的任务" />
      </template>
    </n-data-table>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, h } from 'vue';
import { useTaskStore } from '@/stores/task';
import { NProgress, NTag, NButton, NEmpty } from 'naive-ui';

const taskStore = useTaskStore();

onMounted(() => {
  taskStore.connect();
});

onUnmounted(() => {
  taskStore.disconnect();
});

// --- 辅助函数 ---
const calculatePercentage = (progress, total) => {
  if (total <= 0) return 0;
  return Math.round((progress / total) * 100);
};

const formatTime = (isoString) => {
  if (!isoString) return '-';
  return new Date(isoString).toLocaleString();
};

const getStatusType = (status) => {
  switch (status) {
    case 'running': return 'info'; // Naive UI info 是蓝色
    case 'cancelling': return 'warning';
    case 'completed': return 'success';
    case 'failed': return 'error';
    case 'cancelled': return 'default';
    default: return 'default';
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
  if (status === 'failed') return 'error';
  if (status === 'completed') return 'success';
  return 'default'; // 运行中
};

// --- 列定义 ---
const columns = [
  {
    title: '任务名称',
    key: 'name',
    minWidth: 250,
  },
  {
    title: '进度',
    key: 'progress',
    minWidth: 300,
    render(row) {
      const isIndeterminate = row.total === -1;
      const percentage = isIndeterminate ? 100 : calculatePercentage(row.progress, row.total);
      const status = getProgressStatus(row.status);
      const processing = row.status === 'running' || row.status === 'cancelling';

      // 直接使用 h() 函数创建 Flex 布局
      return h(
        'div',
        {
          style: {
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }
        },
        [
          // 左侧：进度条 (占据剩余空间)
          h(NProgress, {
            type: 'line',
            percentage: percentage,
            indicatorPlacement: 'inside',
            processing: processing,
            status: status,
            height: 20,
            borderRadius: 4,
            style: {
              flexGrow: 1
            }
          }),
          // 右侧：进度文本 (固定宽度，防止挤压)
          h(
            'span',
            {
              style: {
                fontSize: '12px',
                color: 'var(--n-text-color-3)',
                whiteSpace: 'nowrap',
                flexShrink: 0,
                minWidth: '80px',
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums'
              }
            },
            isIndeterminate 
              ? `已处理 ${row.progress}` 
              : `${row.progress} / ${row.total}`
          )
        ]
      );
    }
  },
  {
    title: '开始时间',
    key: 'start_time',
    width: 200,
    render(row) {
      return formatTime(row.start_time);
    }
  },
  {
    title: '状态',
    key: 'status',
    width: 120,
    render(row) {
      return h(
        NTag,
        { type: getStatusType(row.status), bordered: false },
        { default: () => getStatusText(row.status) }
      );
    }
  },
  {
    title: '操作',
    key: 'actions',
    width: 120,
    fixed: 'right',
    render(row) {
      return h(
        NButton,
        {
          type: 'error',
          size: 'small',
          disabled: row.status !== 'running',
          onClick: () => taskStore.cancelTask(row.id)
        },
        { default: () => '取消任务' }
      );
    }
  }
];
</script>

<style scoped>
.task-page-naive {
  padding: 0 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  margin-bottom: 20px;
  flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

.task-table {
  flex-grow: 1;
}


</style>