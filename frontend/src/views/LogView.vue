<!-- frontend/src/views/LogView.vue -->
<template>
  <div class="log-page">
    <div class="page-header">
      <h2>应用日志</h2>
      <p>实时显示应用后端的运行日志，可按级别、类别和日期筛选，最新的日志会显示在最上方。</p>
    </div>

    <!-- 工具栏 -->
    <div class="log-toolbar">
      <div class="left-controls">
        <n-radio-group v-model:value="logLevelProxy" size="small" @update:value="handleLevelChange">
          <n-radio-button value="INFO" label="重要" />
          <n-radio-button value="WARNING" label="警告" />
          <n-radio-button value="ERROR" label="错误" />
          <n-radio-button value="ALL" label="全部" />
        </n-radio-group>

        <n-select
          v-model:value="selectedCategoryProxy"
          placeholder="按任务类别过滤"
          clearable
          filterable
          :options="categoryOptions"
          @update:value="handleCategoryChange"
          size="small"
          style="width: 240px;"
        />

        <n-date-picker
          v-model:formatted-value="selectedDateProxy"
          type="date"
          placeholder="选择日期 (默认今天)"
          value-format="yyyy-MM-dd"
          clearable
          :is-date-disabled="disabledDate"
          size="small"
          style="width: 200px;"
        />
      </div>
      
      <div class="right-controls">
        <!-- 搜索框 -->
        <div class="search-wrapper">
          <n-input
            v-model:value="searchKeywordProxy"
            placeholder="在当前页搜索..."
            clearable
            @input="handleSearchInput"
            size="small"
            class="search-input"
          >
            <template #suffix>
              <span v-if="searchKeywordProxy" class="search-match-count">
                {{ searchMatches.length > 0 ? `${currentMatchIndex + 1} / ${searchMatches.length}` : '0 / 0' }}
              </span>
              <div class="search-nav-buttons">
                <n-button
                  quaternary
                  size="tiny"
                  @click.stop="navigateToMatch('prev')"
                  :disabled="!searchKeywordProxy || searchMatches.length === 0"
                >
                  <template #icon>
                    <n-icon><ArrowUp /></n-icon>
                  </template>
                </n-button>
                <n-button
                  quaternary
                  size="tiny"
                  @click.stop="navigateToMatch('next')"
                  :disabled="!searchKeywordProxy || searchMatches.length === 0"
                >
                  <template #icon>
                    <n-icon><ArrowDown /></n-icon>
                  </template>
                </n-button>
              </div>
            </template>
          </n-input>
          
        </div>

        <n-select 
          v-model:value="pageSizeProxy" 
          @update:value="handlePageSizeChange" 
          placeholder="每页条数" 
          :options="pageSizeOptions"
          size="small"
          style="width: 130px;"
        />
        
        <n-button type="error" size="small" :disabled="logStore.totalLogs === 0" @click="confirmClearLogs">
          <template #icon>
            <n-icon><Delete /></n-icon>
          </template>
          清空日志
        </n-button>
      </div>
    </div>

    <div class="log-container" ref="logContainerRef">
      <div v-if="logStore.logs.length > 0" class="log-content">
        <div 
          v-for="(log, index) in logStore.logs" 
          :key="`${log.timestamp}-${index}`" 
          class="log-line"
          :ref="el => { if (el) logLineRefs[index] = el }"
        >
          <span class="line-number">{{ getLineNumber(index) }}</span>
          <span :class="['log-level', `log-level-${log.level.toLowerCase()}`]">{{ log.level }}:</span>
          <span class="log-timestamp">{{ log.timestamp }}</span>
          <span class="log-separator">-</span>
          <span class="log-category">{{ log.category }}</span>
          <span class="log-arrow">→</span>
          <span class="log-message" v-html="highlightMessage(log.message)"></span>
        </div>
      </div>
      <div v-else class="empty-state">
        <n-empty description="当前筛选条件下无日志" />
      </div>
    </div>

    <!-- 分页器 -->
    <div class="pagination-footer">
       <n-pagination
        v-model:page="currentPageProxy"
        :page-count="logStore.totalPages"
        :page-slot="5"
        @update:page="handlePageChange"
        :disabled="logStore.totalLogs === 0"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, computed, ref, watch, nextTick } from 'vue';
import { ArrowUp, ArrowDown, Delete } from '@element-plus/icons-vue';
import { 
  NRadioGroup, NRadioButton, NSelect, NDatePicker, NInput, 
  // --- 修改：引入 useDialog，移除 NPopconfirm ---
  NButton, NIcon, NPagination, NEmpty, useMessage, useDialog 
  // --- 修改结束 ---
} from 'naive-ui';
import { useLogStore } from '@/stores/log';
import { useDebounceFn } from '@vueuse/core';

const logStore = useLogStore();
const message = useMessage();
const dialog = useDialog();

const logContainerRef = ref(null);
const logLineRefs = ref([]);
const searchMatches = ref([]);
const currentMatchIndex = ref(-1);

// 构造 Naive UI 需要的选项格式
const categoryOptions = computed(() => {
  return logStore.logCategories.map(cat => ({ label: cat, value: cat }));
});

const pageSizeOptions = [
  { label: '500 条/页', value: 500 },
  { label: '1000 条/页', value: 1000 },
  { label: '2000 条/页', value: 2000 },
  { label: '5000 条/页', value: 5000 },
];

// 封装 showMessage 供 store 使用
const showMessageWrapper = (type, text) => {
  if (message[type]) {
    message[type](text);
  }
};

const logLevelProxy = computed({
  get: () => logStore.logLevel,
  set: () => {}
});

const pageSizeProxy = computed({
  get: () => logStore.pageSize,
  set: () => {}
});

const selectedCategoryProxy = computed({
  get: () => logStore.selectedCategory,
  set: () => {}
});

const selectedDateProxy = computed({
  get: () => logStore.selectedDate,
  set: (val) => {
    logStore.setDateAndFetch(val, { showMessage: showMessageWrapper });
  }
});

const searchKeywordProxy = computed({
  get: () => logStore.searchKeyword,
  set: (val) => { logStore.searchKeyword = val; }
});

const currentPageProxy = computed({
  get: () => logStore.currentPage,
  set: (val) => { logStore.currentPage = val; }
});

onMounted(async () => {
  await logStore.fetchLogDates({ showMessage: showMessageWrapper });
  await logStore.fetchLogCategories({ showMessage: showMessageWrapper });
  await logStore.fetchHistoricalLogs(1, { showMessage: showMessageWrapper });
  logStore.connect();
});

onUnmounted(() => {
  logStore.disconnect();
  logStore.searchKeyword = '';
});

watch([() => logStore.logs, () => logStore.searchKeyword], () => {
  updateSearchResults();
}, { deep: true });

const handlePageChange = (page) => {
  logStore.fetchHistoricalLogs(page, { showMessage: showMessageWrapper });
};

const handleLevelChange = (newLevel) => {
  logStore.setLogLevelAndFetch(newLevel, { showMessage: showMessageWrapper });
};

const handleCategoryChange = (newCategory) => {
  logStore.setCategoryAndFetch(newCategory, { showMessage: showMessageWrapper });
};

const handlePageSizeChange = (newPageSize) => {
  logStore.setPageSizeAndFetch(newPageSize, { showMessage: showMessageWrapper });
};

const confirmClearLogs = () => {
  dialog.warning({
    title: '警告',
    content: '确定要清空所有历史和当前日志吗？此操作不可恢复。',
    positiveText: '确定清空',
    negativeText: '取消',
    onPositiveClick: async () => {
      await handleClearLogs();
    }
  });
};

const handleClearLogs = async () => {
  await logStore.clearLogs({ showMessage: showMessageWrapper });
};

const getLineNumber = (index) => {
  const startIndex = logStore.totalLogs - (logStore.currentPage - 1) * logStore.pageSize;
  return startIndex - index;
};

// Naive UI 的 disabledDate 接收时间戳
const disabledDate = (ts) => {
  const date = new Date(ts);
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const dateString = `${yyyy}-${mm}-${dd}`;
  return !logStore.availableDates.includes(dateString);
};

const handleSearchInput = useDebounceFn(() => {
  updateSearchResults();
}, 300);

const updateSearchResults = () => {
  logLineRefs.value = [];
  searchMatches.value = [];
  currentMatchIndex.value = -1;

  if (!logStore.searchKeyword || logStore.logs.length === 0) {
    return;
  }

  const keyword = logStore.searchKeyword.toLowerCase();
  logStore.logs.forEach((log, index) => {
    if (log.message.toLowerCase().includes(keyword)) {
      searchMatches.value.push(index);
    }
  });

  if (searchMatches.value.length > 0) {
    currentMatchIndex.value = 0;
    nextTick(() => {
      scrollToMatch(currentMatchIndex.value);
    });
  }
};

const highlightMessage = (message) => {
  if (!logStore.searchKeyword) {
    return message;
  }
  const keyword = logStore.searchKeyword;
  const regex = new RegExp(`(${keyword.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')})`, 'gi');
  return message.replace(regex, '<mark class="search-highlight">$1</mark>');
};

const navigateToMatch = (direction) => {
  if (searchMatches.value.length === 0) return;

  if (direction === 'next') {
    currentMatchIndex.value = (currentMatchIndex.value + 1) % searchMatches.value.length;
  } else {
    currentMatchIndex.value = (currentMatchIndex.value - 1 + searchMatches.value.length) % searchMatches.value.length;
  }
  scrollToMatch(currentMatchIndex.value);
};

const scrollToMatch = (matchIndex) => {
  const logIndex = searchMatches.value[matchIndex];
  const targetElement = logLineRefs.value[logIndex];
  if (targetElement) {
    targetElement.scrollIntoView({
      behavior: 'smooth',
      block: 'center'
    });
    document.querySelectorAll('.log-line.is-active').forEach(el => el.classList.remove('is-active'));
    targetElement.classList.add('is-active');
  }
};
</script>

<style>
.search-highlight {
  background-color: #fde24b;
  color: #000;
  padding: 1px 2px;
  border-radius: 3px;
}
.dark .search-highlight {
  background-color: #ffe036;
}
.log-line.is-active {
  background-color: rgba(96, 158, 149, 0.2) !important;
  transition: background-color 0.3s ease;
}
</style>

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
  flex-wrap: wrap;
  gap: 10px;
}

.left-controls, .right-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.search-wrapper {
  display: flex;
  align-items: center;
}
.search-input {
  width: 260px;
}
.search-nav-buttons {
  display: flex;
  flex-direction: row;
  align-items: center;
  height: 100%;
  gap: 2px;
  margin-left: 4px;
}
.search-match-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-right: 4px;
  user-select: none;
  white-space: nowrap;
  min-width: 40px;
  text-align: center;
}

.log-container {
  flex-grow: 1;
  background-color: #292A2D; 
  border-radius: 8px;
  padding: 10px 0;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  position: relative;
}

.log-content {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace;
  font-size: 14px;
  color: #bdc1c6;
}

.log-line {
  display: flex;
  align-items: baseline;
  line-height: 1.6;
  padding: 2px 10px;
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

.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}
</style>