<!-- frontend/src/views/UpcomingMediaView.vue (完整文件覆盖) -->
<template>
  <div class="upcoming-page">
    <div class="page-header">
      <div class="header-main">
        <h2>即将上映</h2>
        <p>预览未来即将上映的电影和新剧，订阅感兴趣的内容以接收上映前通知。</p>
      </div>
      <div class="header-actions">
        <el-button @click="isDrawerVisible = true" :icon="Filter">
          筛选与设置
        </el-button>
      </div>
    </div>

    <div class="custom-tabs-container">
      <div class="custom-tabs-nav">
        <div
          class="custom-tab-item"
          :class="{ active: activeTab === 'movies' }"
          @click="activeTab = 'movies'"
        >
          即将上映电影 ({{ store.upcomingMovies.length }})
        </div>
        <div
          class="custom-tab-item"
          :class="{ active: activeTab === 'tv' }"
          @click="activeTab = 'tv'"
        >
          即将上映电视剧 ({{ store.upcomingTvs.length }})
        </div>
        <div
          class="custom-tab-item"
          :class="{ active: activeTab === 'subscriptions' }"
          @click="activeTab = 'subscriptions'"
        >
          我的订阅 ({{ store.subscriptionList.length }})
        </div>
        <div
          class="custom-tab-item"
          :class="{ active: activeTab === 'permanent' }"
          @click="activeTab = 'permanent'"
        >
          永久收藏({{ store.permanentList.length }})
        </div>
      </div>
      <div v-if="activeTab !== 'subscriptions'" class="dynamic-filters">
        <el-select
          v-model="selectedCountry"
          placeholder="按地区过滤"
          clearable
          filterable
          size="small"
          style="width: 180px;"
        >
          <el-option
            v-for="option in countryOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-select
          v-model="selectedGenre"
          placeholder="按类型过滤"
          clearable
          filterable
          size="small"
          style="width: 180px;"
        >
          <el-option
            v-for="option in genreOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button 
          v-if="activeTab === 'permanent'" 
          :icon="Plus" 
          @click="openSearchDialog"
          size="small"
        >
          搜索添加
        </el-button>
      </div>

      <div 
        ref="scrollContainer"
        class="custom-tabs-content" 
        @scroll="handleScroll"
      >
        <ResultsGrid 
          :items="currentItems" 
          :loading="currentLoading" 
          :type="currentType"
          @subscribe="handleSubscribe"
          @unsubscribe="handleUnsubscribe"
          @permanent-toggle="handlePermanentToggle"
        />
        <!-- --- 新增：加载状态显示 --- -->
        <div 
          v-if="isLoadingMore" 
          class="loading-more-container energy-ring-loading-container"
          v-loading="true"
          element-loading-text="正在加载更多..."
          element-loading-background="transparent"
        >
        </div>
        <div v-if="allDataLoaded && activeTab !== 'subscriptions' && !isLoadingMore && currentItems.length > 0" class="all-loaded-tip">
          🎉 已全部加载
        </div>
        <!-- --- 新增结束 --- -->
      </div>
    </div>

    <el-drawer
      v-model="isDrawerVisible"
      title="筛选与设置"
      direction="rtl"
      size="500px"
    >
      <div class="drawer-content">
        <!-- frontend/src/views/UpcomingMediaView.vue (代码块替换) -->

        <el-tabs>
          <el-tab-pane label="筛选条件">
            <el-alert
              title="数据处理流程说明"
              type="info"
              show-icon
              :closable="false"
              style="margin-top: 10px; margin-bottom: 15px;"
            >
              <p style="line-height: 1.6; margin: 0;">
                ➡️ **第一步 (Trakt):** 从 Trakt.tv 获取原始的全球上映日历。<br>
                ➡️ **第二步 (筛选):** 应用下方的筛选条件，对原始日历进行预处理。<br>
                ➡️ **第三步 (TMDB):** 为通过筛选的项目，从 TMDB 获取详细的中文信息和海报。<br>
                <br>
                因此，所有筛选条件均作用于第一步的 Trakt 原始数据。防止过多的请求tmdb api
              </p>
            </el-alert>
            <div class="filter-content">
              <el-form label-position="top">
                <el-form-item label="基础设置">
                  <div class="filter-item-row">
                    <span class="filter-label">获取天数</span>
                    <el-input-number v-model="store.filterOptions.fetch_days" :min="1" :max="30" size="small" />
                  </div>
                </el-form-item>
                <el-form-item label="类型黑名单 (选中项将被过滤)">
                  <el-select
                    v-model="store.filterOptions.genre_blacklist.selected"
                    multiple
                    filterable
                    placeholder="请选择要过滤的类型"
                    style="width: 100%"
                    collapse-tags
                    collapse-tags-tooltip
                  >
                    <el-option
                      v-for="item in store.filterOptions.genre_blacklist.available"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    >
                      <span class="option-label">{{ item.label }}</span>
                      <el-tag v-if="isBuiltIn('genre_blacklist', item.value)" size="small" type="info" effect="plain" class="builtin-tag">内置</el-tag>
                    </el-option>
                  </el-select>
                </el-form-item>
                <el-form-item label="核心市场 (P0)">
                   <p class="group-desc">国家/地区 或 语言 满足其一即可通过</p>
                   <el-select
                    v-model="store.filterOptions.p0_countries.selected"
                    multiple
                    filterable
                    placeholder="选择国家/地区"
                    style="width: 100%; margin-bottom: 10px;"
                    collapse-tags
                    collapse-tags-tooltip
                  >
                    <el-option
                      v-for="item in store.filterOptions.p0_countries.available"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    >
                      <span class="option-label">{{ item.label }}</span>
                      <el-tag v-if="isBuiltIn('p0_countries', item.value)" size="small" type="info" effect="plain" class="builtin-tag">内置</el-tag>
                    </el-option>
                  </el-select>
                  <el-select
                    v-model="store.filterOptions.p0_languages.selected"
                    multiple
                    filterable
                    placeholder="选择语言"
                    style="width: 100%"
                    collapse-tags
                    collapse-tags-tooltip
                  >
                    <el-option
                      v-for="item in store.filterOptions.p0_languages.available"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    >
                      <span class="option-label">{{ item.label }}</span>
                      <el-tag v-if="isBuiltIn('p0_languages', item.value)" size="small" type="info" effect="plain" class="builtin-tag">内置</el-tag>
                    </el-option>
                  </el-select>
                </el-form-item>
                <el-form-item label="潜力市场 (P1)">
                  <p class="group-desc">国家/地区 满足其一 且 必须有中文翻译</p>
                  <el-select
                    v-model="store.filterOptions.p1_countries.selected"
                    multiple
                    filterable
                    placeholder="选择国家/地区"
                    style="width: 100%"
                    collapse-tags
                    collapse-tags-tooltip
                  >
                    <el-option
                      v-for="item in store.filterOptions.p1_countries.available"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    >
                      <span class="option-label">{{ item.label }}</span>
                      <el-tag v-if="isBuiltIn('p1_countries', item.value)" size="small" type="info" effect="plain" class="builtin-tag">内置</el-tag>
                    </el-option>
                  </el-select>
                </el-form-item>
              </el-form>
            </div>
          </el-tab-pane>
          <el-tab-pane label="功能设置">
            <div class="settings-content">
              <el-form label-position="top">
                <el-form-item label="启用订阅通知功能">
                  <el-switch v-model="store.config.enabled" />
                </el-form-item>
                <el-form-item label="通知周期 (CRON 表达式)">
                  <div class="cron-input-group">
                    <el-input v-model="store.config.notification_cron" placeholder="例如: 0 9 * * *" />
                    <el-button @click="handleTriggerNotification" :loading="isTriggeringNotification">立即执行一次</el-button>
                  </div>
                  <div v-if="notificationCronDesc" class="cron-description" :class="{ 'error': notificationCronError }">
                    {{ notificationCronDesc }}
                  </div>
                </el-form-item>
                <el-form-item label="过期项目清理周期 (CRON 表达式)">
                  <div class="cron-input-group">
                    <el-input v-model="store.config.pruning_cron" placeholder="例如: 0 1 * * *" />
                    <el-button @click="handleTriggerPruning" :loading="isTriggeringPruning">立即执行一次</el-button>
                  </div>
                  <div v-if="pruningCronDesc" class="cron-description" :class="{ 'error': pruningCronError }">
                    {{ pruningCronDesc }}
                  </div>
                </el-form-item>
              </el-form>
            </div>
          </el-tab-pane>
          <!-- --- 新增：自动化订阅 Tab --- -->
          <el-tab-pane label="自动化订阅">
            <div class="settings-content">
              <el-form label-position="top" v-if="store.config.auto_subscribe_rules">
                <el-form-item label="启用自动化订阅">
                  <el-switch v-model="store.config.auto_subscribe_rules.enabled" />
                  <div class="form-item-description">
                    开启后，每次后台更新数据时，将根据下方规则自动订阅符合条件的未订阅项目。
                  </div>
                </el-form-item>
                
                <el-divider>规则一：演员匹配 (或逻辑)</el-divider>
                <el-form-item label="关键词演员">
                  <el-select
                    v-model="store.config.auto_subscribe_rules.actors"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="输入演员名后按回车创建"
                    style="width: 100%"
                    :disabled="!store.config.auto_subscribe_rules.enabled"
                  >
                  </el-select>
                   <div class="form-item-description">
                    只要项目的演员列表中包含任何一个您在此处添加的演员，该项目就会被自动订阅。
                  </div>
                </el-form-item>

                <el-divider>规则二：国家与热门度 (与逻辑)</el-divider>
                <el-form-item label="国家/地区">
                  <el-select
                    v-model="store.config.auto_subscribe_rules.countries"
                    multiple
                    filterable
                    placeholder="选择国家/地区"
                    style="width: 100%"
                    :disabled="!store.config.auto_subscribe_rules.enabled"
                  >
                    <el-option
                      v-for="item in countryOptionsForRules"
                      :key="item.value"
                      :label="item.label"
                      :value="item.value"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item>
                  <template #label>
                    <span>热门度 (Popularity) 阈值</span>
                  </template>
                  <el-slider 
                    v-model="store.config.auto_subscribe_rules.min_popularity" 
                    :min="0" 
                    :max="100" 
                    :step="0.1" 
                    show-input
                    :disabled="!store.config.auto_subscribe_rules.enabled"
                  />
                  <div class="form-item-description">
                    <b>提示：</b>TMDB 的“热门度”是一个动态变化的数值。根据经验，对于<b>未上映</b>的影视剧：<br>
                    • <b>0 - 5</b>：普通关注度<br>
                    • <b>5 - 15</b>：较高关注度 (如热门剧集)<br>
                    • <b>15 - 40</b>：非常热门 (如漫威电影)<br>
                    • <b>40+</b>：现象级作品<br>
                    建议初始值设置为 <b>5.0</b> 左右进行尝试。
                  </div>
                </el-form-item>
              </el-form>
            </div>
          </el-tab-pane>
          <!-- --- 新增结束 --- -->
        </el-tabs>
      
      </div>
      <div class="drawer-footer">
        <el-button @click="store.resetFilters">重置筛选</el-button>
        <el-button @click="handleSaveSettings" :loading="store.isSaving">保存设置</el-button>
        <el-button type="primary" @click="handleApplyFilters" :loading="store.isListLoading">应用筛选</el-button>
      </div>
    </el-drawer>
    <el-dialog
      v-model="isSearchDialogVisible"
      title="搜索并添加永久收藏"
      width="70%"
      top="5vh"
    >
      <div class="search-add-dialog">
        <div class="search-controls">
          <div class="media-type-selector">
            <el-radio-group v-model="searchMediaType">
              <el-radio-button value="movie">电影</el-radio-button>
              <el-radio-button value="tv">电视剧</el-radio-button>
            </el-radio-group>
          </div>
          <el-input
            v-model="searchQuery"
            placeholder="输入标题或 TMDB ID..."
            clearable
            @keyup.enter="handleSearch"
            style="flex-grow: 1;"
          />
          <el-button type="primary" @click="handleSearch" :loading="store.isSearching">搜索</el-button>
        </div>
        <div 
          class="search-results-container energy-ring-loading-container" 
          v-loading="store.isSearching"
          element-loading-text="正在搜索..."
          element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
        >
          <el-table
            :data="store.searchResults"
            height="100%"
            highlight-current-row
            @current-change="handleSelectionChange"
            empty-text="请输入关键词进行搜索"
          >
            <el-table-column label="海报" width="80">
              <template #default="scope">
                <el-image 
                  :src="scope.row.poster_path ? `https://image.tmdb.org/t/p/w200${scope.row.poster_path}` : ''" 
                  fit="cover" 
                  style="width: 50px; height: 75px; border-radius: 4px;"
                >
                  <template #error><div class="image-slot-error">无图</div></template>
                </el-image>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" />
            <el-table-column prop="release_date" label="上映日期" width="120" />
            <el-table-column prop="overview" label="简介" show-overflow-tooltip />
          </el-table>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="isSearchDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="handleAddItem" :disabled="!selectedSearchItem">
            添加选中项
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>


<script setup>
import { onMounted, ref, computed, watch } from 'vue';
import { useStorage } from '@vueuse/core';
import { useUpcomingStore } from '@/stores/upcoming';
import { Filter, Plus } from '@element-plus/icons-vue';
import ResultsGrid from '@/components/ResultsGrid.vue';
import cronstrue from 'cronstrue/i18n';
import { COUNTRY_MAP } from '@/config/filterConstants';

const store = useUpcomingStore();
const activeTab = useStorage('upcoming-active-tab', 'movies');
const isDrawerVisible = ref(false);

const selectedCountry = ref('');
const selectedGenre = ref('');

// --- 新增：无限滚动状态 ---
const itemsPerPage = 15;
const currentPage = ref(1);
const isLoadingMore = ref(false);
const allDataLoaded = ref(false);
const scrollContainer = ref(null); // 用于获取滚动容器的 DOM 引用

const isSearchDialogVisible = ref(false);
const searchMediaType = ref('movie');
const searchQuery = ref('');
const selectedSearchItem = ref(null);

const openSearchDialog = () => {
  searchQuery.value = '';
  store.searchResults = [];
  selectedSearchItem.value = null;
  isSearchDialogVisible.value = true;
};

const handleSearch = () => {
  if (!searchQuery.value) {
    store.showMessage('warning', '请输入搜索内容！');
    return;
  }
  store.searchTmdb(searchMediaType.value, searchQuery.value);
};

const handleSelectionChange = (item) => {
  selectedSearchItem.value = item;
};

const handleAddItem = async () => {
  if (!selectedSearchItem.value) {
    store.showMessage('warning', '请先从列表中选择一个项目！');
    return;
  }
  const success = await store.addPermanentItem(selectedSearchItem.value, searchMediaType.value);
  if (success) {
    isSearchDialogVisible.value = false;
  }
};

const countryOptions = computed(() => {
  const countries = new Set();
  baseItems.value.forEach(item => {
    item.origin_country?.forEach(code => countries.add(code));
  });
  return Array.from(countries).map(code => ({
    value: code,
    label: COUNTRY_MAP[code.toLowerCase()] || code
  })).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
});

const genreOptions = computed(() => {
  const genres = new Set();
  baseItems.value.forEach(item => {
    item.genres?.forEach(name => genres.add(name));
  });
  return Array.from(genres).map(name => ({
    value: name,
    label: name
  })).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
});
const notificationCronDesc = ref('');
const notificationCronError = ref(false);
const pruningCronDesc = ref('');
const pruningCronError = ref(false);
const isTriggeringNotification = ref(false);
const isTriggeringPruning = ref(false);

const baseItems = computed(() => {
  switch (activeTab.value) {
    case 'movies': return store.upcomingMovies;
    case 'tv': return store.upcomingTvs;
    case 'subscriptions': return store.subscriptionList;
    case 'permanent': return store.permanentList;
    default: return [];
  }
});


const currentItems = computed(() => {
  let items = [...baseItems.value]; // 从基础列表开始

  // 应用地区和类型过滤
  if (selectedCountry.value) {
    items = items.filter(item => item.origin_country?.includes(selectedCountry.value));
  }
  if (selectedGenre.value) {
    items = items.filter(item => item.genres?.includes(selectedGenre.value));
  }
  
  // 订阅和收藏页不分页
  if (['subscriptions', 'permanent'].includes(activeTab.value)) {
    allDataLoaded.value = true;
    return items;
  }

  // 其他页面应用分页
  allDataLoaded.value = (currentPage.value * itemsPerPage) >= items.length;
  return items.slice(0, currentPage.value * itemsPerPage);
});

const currentLoading = computed(() => {
  return activeTab.value === 'subscriptions' ? store.isLoading : store.isListLoading;
});

const currentType = computed(() => {
  return activeTab.value === 'subscriptions' ? 'subscription' : 'default';
});

// --- 核心修正：将 parseCron 函数定义移到最前面 ---
const parseCron = (cron, descRef, errorRef) => {
  if (!cron || cron.trim() === '') {
    descRef.value = '';
    errorRef.value = false;
    return;
  }
  try {
    descRef.value = cronstrue.toString(cron, { locale: "zh_CN" });
    errorRef.value = false;
  } catch (e) {
    descRef.value = `表达式无效: ${e}`;
    errorRef.value = true;
  }
};

onMounted(async () => {
  await store.fetchConfig();
  await store.fetchAllData();
  if (store.allData.length === 0) {
    console.log("检测到本地数据为空，将自动触发一次数据初始化...");
    await store.fetchUpcomingList(true);
  }
});

watch(() => store.config.notification_cron, (newCron) => {
  parseCron(newCron, notificationCronDesc, notificationCronError);
}, { immediate: true });

watch(() => store.config.pruning_cron, (newCron) => {
  parseCron(newCron, pruningCronDesc, pruningCronError);
}, { immediate: true });

const handleApplyFilters = () => {
  store.fetchUpcomingList(false);
  isDrawerVisible.value = false;
};

const handleSaveSettings = async () => {
  const success = await store.saveConfig(store.config);
  if (success) {
    isDrawerVisible.value = false;
  }
};

const isBuiltIn = (key, value) => {
  return store.filterOptions[key]?.builtIn.includes(value);
};

const handleSubscribe = (item) => {
  store.updateSubscription(item, true);
};

const handleUnsubscribe = (item) => {
  store.updateSubscription(item, false);
};

const handlePermanentToggle = (item) => {
  store.togglePermanence(item, !item.is_permanent);
};

const handleTriggerNotification = async () => {
  isTriggeringNotification.value = true;
  await store.triggerNotification();
  isTriggeringNotification.value = false;
};

const handleTriggerPruning = async () => {
  isTriggeringPruning.value = true;
  await store.triggerPruning();
  isTriggeringPruning.value = false;
};

const handleScroll = (event) => {
  // --- 修改 ---
  if (['subscriptions', 'permanent'].includes(activeTab.value) || isLoadingMore.value || allDataLoaded.value) {
    return;
  }

  const container = event.target;
  const threshold = 100;
  const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;

  if (isAtBottom) {
    loadMore();
  }
};

const loadMore = () => {
  isLoadingMore.value = true;
  setTimeout(() => {
    currentPage.value++;
    isLoadingMore.value = false;
  }, 500);
};

const countryOptionsForRules = computed(() => {
  return Object.entries(COUNTRY_MAP).map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
});

watch([activeTab, selectedCountry, selectedGenre], () => {
  currentPage.value = 1;
  allDataLoaded.value = false;
  if (scrollContainer.value) {
    scrollContainer.value.scrollTop = 0;
  }
});
</script>

<style scoped>
.upcoming-page {
  padding: 0 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.header-main h2 { margin: 0 0 8px 0; }
.header-main p { margin: 0; color: var(--el-text-color-secondary); }

.custom-tabs-container {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  margin-top: 20px;
  background-color: var(--el-bg-color-overlay);
}
.custom-tabs-nav {
  display: flex;
  border-bottom: 1px solid var(--el-border-color);
  flex-shrink: 0;
  padding: 0 10px;
}
.custom-tab-item {
  padding: 0 20px;
  height: 40px;
  line-height: 40px;
  cursor: pointer;
  transition: color 0.3s;
  color: var(--el-text-color-regular);
  border-bottom: 2px solid transparent;
}
.custom-tab-item:hover {
  color: var(--el-color-primary);
}
.custom-tab-item.active {
  color: var(--el-color-primary);
  border-bottom-color: var(--el-color-primary);
}
.custom-tabs-content {
  flex-grow: 1;
  overflow-y: auto;
  position: relative;
}

.header-actions{
    margin-right: 50px;
}
.drawer-content {
  padding: 0 20px;
  height: calc(100% - 70px);
  overflow-y: auto;
}
.drawer-footer {
  padding: 10px 20px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background-color: var(--el-drawer-bg-color);
}

.filter-content, .settings-content {
  padding-top: 10px;
}
.group-desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: -5px;
  margin-bottom: 10px;
}
.filter-item-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.filter-label {
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.option-label {
  float: left;
}
.builtin-tag {
  float: right;
  margin-left: 8px;
}
.cron-description {
  font-size: 12px;
  color: var(--el-color-success);
  margin-top: 5px;
  padding: 5px 8px;
  background-color: var(--el-color-success-light-9);
  border-radius: 4px;
  line-height: 1.4;
}
.cron-description.error {
  color: var(--el-color-error);
  background-color: var(--el-color-error-light-9);
}.dynamic-filters {
  display: flex;
  gap: 15px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--el-border-color);
  flex-shrink: 0;
  background-color: var(--el-fill-color-lighter);
}.loading-more-container {
  height: 80px;
  width: 100%;
  flex-shrink: 0;
}

.all-loaded-tip {
  text-align: center;
  padding: 20px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}.cron-input-group {
  display: flex;
  gap: 10px;
  width: 100%;
}
.search-add-dialog {
  height: 65vh;
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.search-controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-shrink: 0;
}
.media-type-selector {
  flex-shrink: 0; /* 防止被压缩 */
}
.media-type-selector .el-radio-group {
  display: flex; /* 确保内部也是 flex 布局 */
}
.media-type-selector .el-radio-button:first-child :deep(.el-radio-button__inner) {
  border-top-left-radius: 4px;
  border-bottom-left-radius: 4px;
}
.media-type-selector .el-radio-button:last-child :deep(.el-radio-button__inner) {
  border-top-right-radius: 4px;
  border-bottom-right-radius: 4px;
}
.search-results-container {
  flex-grow: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}
.image-slot-error {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>