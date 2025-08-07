<!-- frontend/src/views/LogView.vue (完整文件覆盖) -->
<template>
  <div class="log-page">
    <div class="page-header">
      <h2>应用日志</h2>
      <p>实时显示应用后端的运行日志，可按级别、类别和日期筛选，最新的日志会显示在最上方。</p>
    </div>

    <!-- 工具栏 -->
    <div class="log-toolbar">
      <div class="left-controls">
        <el-radio-group v-model="logLevelProxy" @change="handleLevelChange">
          <el-radio-button label="INFO">重要</el-radio-button>
          <el-radio-button label="WARNING">警告</el-radio-button>
          <el-radio-button label="ERROR">错误</el-radio-button>
          <el-radio-button label="ALL">全部</el-radio-button>
        </el-radio-group>

        <el-select
          v-model="selectedCategoryProxy"
          placeholder="按任务类别过滤"
          clearable
          filterable
          @change="handleCategoryChange"
          style="width: 240px;"
        >
          <el-option
            v-for="category in logStore.logCategories"
            :key="category"
            :label="category"
            :value="category"
          />
        </el-select>

        <el-date-picker
          v-model="selectedDateProxy"
          type="date"
          placeholder="选择日期 (默认今天)"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          :clearable="true"
          @change="handleDateChange"
          :disabled-date="disabledDate"
          style="width: 200px;"
        />
      </div>
      <div class="right-controls">
        <!-- --- 核心修改：重构搜索框样式 --- -->
        <el-input
          v-model="searchKeywordProxy"
          placeholder="在当前页搜索..."
          clearable
          @input="handleSearchInput"
          class="search-input"
        >
          <template #suffix>
            <div class="search-nav-buttons">
              <el-button
                link
                :icon="ArrowUp"
                @click.stop="navigateToMatch('prev')"
                :disabled="!searchKeywordProxy || searchMatches.length === 0"
              />
              <el-button
                link
                :icon="ArrowDown"
                @click.stop="navigateToMatch('next')"
                :disabled="!searchKeywordProxy || searchMatches.length === 0"
              />
            </div>
          </template>
        </el-input>
        <span v-if="searchKeywordProxy" class="search-match-count">
          {{ searchMatches.length > 0 ? `${currentMatchIndex + 1} / ${searchMatches.length}` : '0 / 0' }}
        </span>
        <!-- --- 修改结束 --- -->

        <el-select 
          v-model="pageSizeProxy" 
          @change="handlePageSizeChange" 
          placeholder="每页条数" 
          style="width: 120px;"
        >
          <el-option :value="500" label="500 条/页" />
          <el-option :value="1000" label="1000 条/页" />
          <el-option :value="2000" label="2000 条/页" />
          <el-option :value="5000" label="5000 条/页" />
        </el-select>
        <el-button type="danger" @click="logStore.clearLogs" :disabled="logStore.totalLogs === 0">清空日志</el-button>
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
      <el-empty v-else description="当前筛选条件下无日志" />
    </div>

    <!-- 分页器 -->
    <div class="pagination-footer">
       <el-pagination
        v-model:current-page="currentPageProxy"
        :page-size="logStore.pageSize"
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
// --- 核心修改：导入新图标 ---
import { onMounted, onUnmounted, computed, ref, watch, nextTick } from 'vue';
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue';
// --- 修改结束 ---
import { useLogStore } from '@/stores/log';
import { useDebounceFn } from '@vueuse/core';

const logStore = useLogStore();

const logContainerRef = ref(null);
const logLineRefs = ref([]);
const searchMatches = ref([]);
const currentMatchIndex = ref(-1);

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
  set: () => {}
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
  await logStore.fetchLogDates();
  await logStore.fetchLogCategories();
  await logStore.fetchHistoricalLogs(1);
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
  logStore.fetchHistoricalLogs(page);
};

const handleLevelChange = (newLevel) => {
  logStore.setLogLevelAndFetch(newLevel);
};

const handleCategoryChange = (newCategory) => {
  logStore.setCategoryAndFetch(newCategory);
};

const handleDateChange = (newDate) => {
  logStore.setDateAndFetch(newDate);
};

const handlePageSizeChange = (newPageSize) => {
  logStore.setPageSizeAndFetch(newPageSize);
};

const getLineNumber = (index) => {
  const startIndex = logStore.totalLogs - (logStore.currentPage - 1) * logStore.pageSize;
  return startIndex - index;
};

const disabledDate = (time) => {
  const date = new Date(time);
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
  gap: 15px;
  flex-wrap: wrap;
}

/* --- 核心修改：搜索框相关样式 --- */
.search-input {
  width: 200px;
}
.search-nav-buttons {
  display: flex;
  flex-direction: column;
  justify-content: center;
  height: 100%;
  margin-right: -5px; /* 微调，使按钮更贴近边缘 */
}
.search-nav-buttons .el-button {
  padding: 0;
  margin: 0;
  height: 14px;
  font-size: 12px;
  width: 20px;
}
.search-nav-buttons .el-button + .el-button {
  margin-left: 0;
}
.search-match-count {
  font-size: 14px;
  color: var(--el-text-color-secondary);
  margin-left: -5px;
  margin-right: 5px;
  user-select: none;
}
/* --- 修改结束 --- */

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

.log-container :deep(.el-empty) {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
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