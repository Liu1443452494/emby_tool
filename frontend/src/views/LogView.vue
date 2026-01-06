<!-- frontend/src/views/LogView.vue (完整文件覆盖 - 最终重构版) -->
<template>
  <div class="log-page-naive">
    <div class="page-header">
      <h2>应用日志</h2>
      <p>实时显示应用后端的运行日志，可按级别、类别和日期筛选，最新的日志会显示在最上方。</p>
    </div>

    <!-- 工具栏 -->
    <n-space class="log-toolbar" justify="space-between" align="center">
      <n-space>
        <n-radio-group v-model:value="logLevel">
          <n-radio-button value="INFO">重要</n-radio-button>
          <n-radio-button value="WARNING">警告</n-radio-button>
          <n-radio-button value="ERROR">错误</n-radio-button>
          <n-radio-button value="ALL">全部</n-radio-button>
        </n-radio-group>

        <n-select
          v-model:value="selectedCategory"
          placeholder="按任务类别过滤"
          :options="categoryOptions"
          clearable
          filterable
          style="width: 240px;"
        />

        <n-date-picker
          v-model:formatted-value="selectedDate"
          type="date"
          placeholder="选择日期 (默认今天)"
          value-format="yyyy-MM-dd"
          clearable
          :is-date-disabled="isDateDisabled"
          style="width: 200px;"
        />
      </n-space>
      <n-space>
        <n-input
          v-model:value="searchKeyword"
          placeholder="在当前页搜索..."
          clearable
        >
          <template #suffix>
            <span class="search-match-count">
              {{ searchKeyword ? `${filteredLogs.length} / ${logStore.logs.length}` : '' }}
            </span>
          </template>
        </n-input>

        <n-select 
          v-model:value="pageSize" 
          :options="pageSizeOptions"
          style="width: 120px;"
        />
        <n-button type="error" @click="handleClearLogs" :disabled="logStore.totalLogs === 0">清空日志</n-button>
      </n-space>
    </n-space>

    <div class="log-container">
      <!-- --- 核心修改：添加动态 :key --- -->
      <n-virtual-list 
        v-if="filteredLogs.length > 0" 
         :key="`${logLevel}-${selectedCategory}-${selectedDate}-${pageSize}-${currentPage}`"
        :items="filteredLogs" 
        :item-size="26" 
        item-resizable
        style="height: 100%;"
      >
        <template #default="{ item: log, index }">
          <div :key="`${log.timestamp}-${index}`" class="log-line-wrapper">
            <div class="log-line">
              <span class="line-number">{{ getLineNumber(index) }}</span>
              <span :class="['log-level', `log-level-${log.level.toLowerCase()}`]">{{ log.level }}:</span>
              <span class="log-timestamp">{{ log.timestamp }}</span>
              <span class="log-separator">-</span>
              <span class="log-category">{{ log.category }}</span>
              <span class="log-arrow">→</span>
              <!-- 核心样式：white-space: pre-wrap 确保换行符被渲染 -->
              <span class="log-message" v-html="highlightMessage(log.message)"></span>
            </div>
          </div>
        </template>
      </n-virtual-list>
      <n-empty v-else description="当前筛选条件下无日志" class="log-empty" />
    </div>

    <!-- 分页器 -->
    <div class="pagination-footer">
       <n-pagination
        v-model:page="currentPage"
        v-model:page-size="pageSize"
        :item-count="logStore.totalLogs"
        show-quick-jumper
        show-size-picker
        :page-sizes="[500, 1000, 2000, 5000]"
        :disabled="logStore.totalLogs === 0"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, computed, ref, watch } from 'vue';
import { useLogStore } from '@/stores/log';
import { useMessage, useDialog } from 'naive-ui';

const logStore = useLogStore();
const message = useMessage();
const dialog = useDialog();

const showMessage = (type, content) => {
  message[type](content, { duration: 3000, closable: true });
};

const storeOptions = { showMessage };

// --- 响应式状态代理 ---
const logLevel = ref(logStore.logLevel);
const selectedCategory = ref(logStore.selectedCategory);
const selectedDate = ref(logStore.selectedDate);
const searchKeyword = ref(logStore.searchKeyword);
const pageSize = ref(logStore.pageSize);
const currentPage = ref(logStore.currentPage);

// --- 计算属性 ---
const categoryOptions = computed(() => 
  logStore.logCategories.map(cat => ({ label: cat, value: cat }))
);

const pageSizeOptions = [
  { label: '500 条/页', value: 500 },
  { label: '1000 条/页', value: 1000 },
  { label: '2000 条/页', value: 2000 },
  { label: '5000 条/页', value: 5000 },
];

const filteredLogs = computed(() => {
  if (!searchKeyword.value) {
    return logStore.logs;
  }
  const keyword = searchKeyword.value.toLowerCase();
  return logStore.logs.filter(log => 
    log.message.toLowerCase().includes(keyword) ||
    log.category.toLowerCase().includes(keyword)
  );
});

// --- 生命周期钩子 ---
onMounted(async () => {
  await logStore.fetchLogDates(storeOptions);
  await logStore.fetchLogCategories(storeOptions);
  await logStore.fetchHistoricalLogs(1, storeOptions);
  logStore.connect();
});

onUnmounted(() => {
  logStore.disconnect();
  logStore.searchKeyword = '';
});

// --- 监听器 ---
watch(logLevel, (newLevel) => logStore.setLogLevelAndFetch(newLevel, storeOptions));
watch(selectedCategory, (newCategory) => logStore.setCategoryAndFetch(newCategory, storeOptions));
watch(selectedDate, (newDate) => logStore.setDateAndFetch(newDate, storeOptions));
watch(pageSize, (newPageSize) => {
  currentPage.value = 1;
  logStore.setPageSizeAndFetch(newPageSize, storeOptions);
});
watch(currentPage, (newPage) => logStore.fetchHistoricalLogs(newPage, storeOptions));

// --- 方法 ---
const getLineNumber = (index) => {
  const startIndex = logStore.totalLogs - (logStore.currentPage - 1) * logStore.pageSize;
  return startIndex - index;
};

const highlightMessage = (msg) => {
  if (!searchKeyword.value) {
    return msg;
  }
  const keyword = searchKeyword.value;
  const regex = new RegExp(`(${keyword.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')})`, 'gi');
  return msg.replace(regex, '<mark class="search-highlight">$1</mark>');
};

const isDateDisabled = (ts) => {
  const date = new Date(ts);
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const dateString = `${yyyy}-${mm}-${dd}`;
  return !logStore.availableDates.includes(dateString);
};

const handleClearLogs = () => {
  dialog.warning({
    title: '警告',
    content: '确定要清空所有历史和当前日志吗？此操作不可恢复。',
    positiveText: '确定清空',
    negativeText: '取消',
    onPositiveClick: async () => {
      const success = await logStore.clearLogs(storeOptions);
      if (success) {
        currentPage.value = 1;
      }
    },
  });
};
</script>

<style>
.search-highlight {
  background-color: #fde24b;
  color: #000;
  padding: 0 2px;
  border-radius: 3px;
}
.dark .search-highlight {
  background-color: #ffe036;
}
</style>

<style scoped>
.log-page-naive {
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
  padding: 15px 0;
  flex-shrink: 0;
}

.search-match-count {
  font-size: 12px;
  color: var(--n-suffix-text-color);
  white-space: nowrap;
}

.log-container {
  flex-grow: 1;
  background-color: #292A2D; 
  border-radius: 8px;
  padding: 10px 0;
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  position: relative;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace;
  font-size: 14px;
  color: #bdc1c6;
}

.log-empty {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

/* --- 核心样式 --- */
.log-line-wrapper {
  width: 100%;
  /* 确保 wrapper 不会限制内部内容的高度 */
  box-sizing: border-box;
}

.log-line {
  display: flex;
  /* 关键：使用 baseline 对齐，确保第一行文字与时间戳对齐 */
  align-items: baseline; 
  line-height: 1.6;
  padding: 2px 10px;
  box-sizing: border-box;
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
  width: 65px;
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
  width: 230px;
  color: #8ab4f8;
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
  /* 关键：使用 pre-wrap 保留换行符和空格，这与您源代码中的行为一致 */
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
</style>