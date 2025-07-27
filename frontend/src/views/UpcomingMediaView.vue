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
          电影 ({{ store.upcomingMovies.length }})
        </div>
        <div
          class="custom-tab-item"
          :class="{ active: activeTab === 'tv' }"
          @click="activeTab = 'tv'"
        >
          电视剧 ({{ store.upcomingTvs.length }})
        </div>
        <div
          class="custom-tab-item"
          :class="{ active: activeTab === 'subscriptions' }"
          @click="activeTab = 'subscriptions'"
        >
          我的订阅 ({{ store.subscriptionList.length }})
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
      </div>

      <div class="custom-tabs-content">
        <ResultsGrid 
          :items="currentItems" 
          :loading="currentLoading" 
          :type="currentType"
          @subscribe="handleSubscribe"
          @unsubscribe="handleUnsubscribe"
        />
      </div>
    </div>

    <el-drawer
      v-model="isDrawerVisible"
      title="筛选与设置"
      direction="rtl"
      size="500px"
    >
      <div class="drawer-content">
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
                  <el-input v-model="store.config.notification_cron" placeholder="例如: 0 9 * * *" />
                  <div v-if="notificationCronDesc" class="cron-description" :class="{ 'error': notificationCronError }">
                    {{ notificationCronDesc }}
                  </div>
                </el-form-item>
                <el-form-item label="过期项目清理周期 (CRON 表达式)">
                  <el-input v-model="store.config.pruning_cron" placeholder="例如: 0 1 * * *" />
                  <div v-if="pruningCronDesc" class="cron-description" :class="{ 'error': pruningCronError }">
                    {{ pruningCronDesc }}
                  </div>
                </el-form-item>
              </el-form>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <div class="drawer-footer">
        <el-button @click="store.resetFilters">重置筛选</el-button>
        <el-button @click="handleSaveSettings" :loading="store.isSaving">保存设置</el-button>
        <el-button type="primary" @click="handleApplyFilters" :loading="store.isListLoading">应用筛选</el-button>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { onMounted, ref, computed, watch } from 'vue';
import { useUpcomingStore } from '@/stores/upcoming';
import { Filter } from '@element-plus/icons-vue';
import ResultsGrid from '@/components/ResultsGrid.vue';
import { useStorage } from '@vueuse/core';
import cronstrue from 'cronstrue/i18n';
import { COUNTRY_MAP } from '@/config/filterConstants';

const store = useUpcomingStore();
const activeTab = useStorage('upcoming-active-tab', 'movies');
const isDrawerVisible = ref(false);

const selectedCountry = ref('');
const selectedGenre = ref('');

const countryOptions = computed(() => {
  const items = activeTab.value === 'movies' ? store.upcomingMovies : store.upcomingTvs;
  const countries = new Set();
  items.forEach(item => {
    item.origin_country?.forEach(code => countries.add(code));
  });
  return Array.from(countries).map(code => ({
    value: code,
    label: COUNTRY_MAP[code.toLowerCase()] || code
  })).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'));
});

const genreOptions = computed(() => {
  const items = activeTab.value === 'movies' ? store.upcomingMovies : store.upcomingTvs;
  const genres = new Set();
  items.forEach(item => {
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
  // --- 修改：增加智能刷新逻辑 ---
  await store.fetchAllData();
  if (store.allData.length === 0) {
    console.log("检测到本地数据为空，将自动触发一次数据初始化...");
    await store.fetchUpcomingList(true); // 使用默认配置进行首次数据获取
  }
  // --- 修改结束 ---
});

watch(() => store.config.notification_cron, (newCron) => {
  parseCron(newCron, notificationCronDesc, notificationCronError);
}, { immediate: true });

watch(() => store.config.pruning_cron, (newCron) => {
  parseCron(newCron, pruningCronDesc, pruningCronError);
}, { immediate: true });

const currentItems = computed(() => {
  let items;
  switch (activeTab.value) {
    case 'movies': 
      items = store.upcomingMovies;
      break;
    case 'tv': 
      items = store.upcomingTvs;
      break;
    case 'subscriptions': 
      return store.subscriptionList; // 订阅列表不参与过滤
    default: 
      return [];
  }

  if (selectedCountry.value) {
    items = items.filter(item => item.origin_country?.includes(selectedCountry.value));
  }
  if (selectedGenre.value) {
    items = items.filter(item => item.genres?.includes(selectedGenre.value));
  }
  
  return items;
});

const currentLoading = computed(() => {
  return activeTab.value === 'subscriptions' ? store.isLoading : store.isListLoading;
});

const currentType = computed(() => {
  return activeTab.value === 'subscriptions' ? 'subscription' : 'default';
});

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
}
</style>