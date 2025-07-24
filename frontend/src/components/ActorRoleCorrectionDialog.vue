<!-- frontend/src/components/ActorRoleCorrectionDialog.vue (完整文件覆盖 - 状态切换版) -->
<template>
  <el-dialog
    :model-value="visible"
    title="手动校正角色名"
    width="85%"
    top="5vh"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
    @closed="resetState"
    class="correction-dialog"
  >
    <div class="dialog-layout">
      <!-- 步骤一：媒体选择 -->
      <div class="step-panel">
        <div class="step-header">
          <div class="step-number">1</div>
          <h4>选择媒体</h4>
        </div>
        <el-form @submit.prevent="handleSearch" class="search-form">
          <el-input v-model="searchQuery" placeholder="输入标题或ItemID..." clearable />
          <el-button type="primary" native-type="submit" :loading="isSearching">搜索</el-button>
        </el-form>
        <div class="actor-limit-control">
          <span>仅加载前</span>
          <el-input-number 
            v-model="actorLoadLimit" 
            :min="5" 
            :max="100" 
            size="small"
            controls-position="right"
            style="width: 90px;"
          />
          <span>位主要演员</span>
        </div>
        <div 
          class="search-results-table energy-ring-loading-container" 
          v-loading="isSearching"
          element-loading-text="正在搜索..."
          element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
        >
          <el-table
            :data="searchResults"
            height="100%"
            highlight-current-row
            @current-change="handleMediaSelection"
            empty-text="请输入关键词搜索"
          >
            <el-table-column prop="Name" label="标题" show-overflow-tooltip />
            <el-table-column prop="ProductionYear" label="年份" width="70" />
          </el-table>
        </div>
      </div>

      <!-- 步骤二：角色校对 -->
      <div class="step-panel">
        <div class="step-header">
          <div class="step-number">2</div>
          <h4>校对角色</h4>
        </div>
        <div class="correction-toolbar">
          <el-button 
            type="primary" 
            @click="handleAiSuggest" 
            :loading="isSuggesting"
            :disabled="!selectedMedia || selectionForAi.length === 0"
          >
            AI填充建议 (选中 {{ selectionForAi.length }} 项)
          </el-button>
          <el-button 
            type="success" 
            @click="handleApplyToEmby" 
            :loading="isApplying"
            :disabled="!selectedMedia || applyableCount === 0"
          >
            应用到 Emby ({{ applyableCount }} 项)
          </el-button>
        </div>
        <div 
          class="correction-table-container energy-ring-loading-container" 
          v-loading="isLoadingPeople || isSuggesting"
          :element-loading-text="isLoadingPeople ? '正在加载演员列表...' : '正在请求AI建议...'"
          element-loading-background="rgba(var(--custom-bg-overlay-rgb), 0.7)"
        >
          <el-table 
            :data="people" 
            height="100%" 
            stripe
            ref="correctionTableRef"
            @selection-change="handleAiSelectionChange"
          >
            <el-table-column type="selection" width="55" />
            <el-table-column label="头像" width="80">
              <template #default="scope">
                <el-avatar shape="square" :size="50" :src="getAvatarUrl(scope.row)" />
              </template>
            </el-table-column>
            <el-table-column prop="Name" label="演员名" width="180" />
            <el-table-column prop="Role" label="当前角色名" />
            <el-table-column label="新角色名 (可编辑)">
              <template #default="scope">
                <el-input v-model="scope.row.NewRole" placeholder="AI建议或手动输入" />
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="scope">
                <el-tag 
                  :type="getStatusInfo(scope.row).type" 
                  :effect="getStatusInfo(scope.row).effect"
                  @click="toggleStatus(scope.row)"
                  :style="{ cursor: getStatusInfo(scope.row).clickable ? 'pointer' : 'default' }"
                  disable-transitions
                >
                  {{ getStatusInfo(scope.row).text }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue';
import { ElMessage } from 'element-plus';
import { API_BASE_URL } from '@/config/apiConfig';
import { useStorage } from '@vueuse/core';

const props = defineProps({
  visible: Boolean,
});
const emit = defineEmits(['update:visible']);

const searchQuery = ref('');
const isSearching = ref(false);
const searchResults = ref([]);
const selectedMedia = ref(null);

const isLoadingPeople = ref(false);
const people = ref([]);
const actorLoadLimit = useStorage('actor-correction-load-limit', 15);

const isSuggesting = ref(false);
const isApplying = ref(false);

const selectionForAi = ref([]);
const correctionTableRef = ref(null);

const applyableCount = computed(() => people.value.filter(p => p.status === 'changed').length);

watch(() => props.visible, (newVal) => {
  if (!newVal) {
    resetState();
  }
});

// 监听 NewRole 的变化，自动管理 status
watch(people, (newPeople) => {
  newPeople.forEach(person => {
    const isChanged = person.Role !== person.NewRole;
    if (isChanged && person.status !== 'ignored') {
      person.status = 'changed';
    } else if (!isChanged) {
      person.status = 'unchanged';
    }
  });
}, { deep: true });

function resetState() {
  searchQuery.value = '';
  searchResults.value = [];
  selectedMedia.value = null;
  people.value = [];
  isLoadingPeople.value = false;
  isSuggesting.value = false;
  isApplying.value = false;
  selectionForAi.value = [];
}

async function handleSearch() {
  if (!searchQuery.value) return;
  isSearching.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/media/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: searchQuery.value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '搜索失败');
    searchResults.value = data;
  } catch (error) {
    ElMessage.error(`搜索失败: ${error.message}`);
  } finally {
    isSearching.value = false;
  }
}

async function handleMediaSelection(media) {
  if (!media || (selectedMedia.value && selectedMedia.value.Id === media.Id)) return;
  selectedMedia.value = media;
  isLoadingPeople.value = true;
  people.value = [];
  try {
    const response = await fetch(`${API_BASE_URL}/api/actor-localizer/media/${media.Id}/people`);
    if (!response.ok) throw new Error((await response.json()).detail || '获取演员列表失败');
    const peopleData = await response.json();
    
    const actors = peopleData.filter(p => p.Type === 'Actor');
    const slicedActors = actors.slice(0, actorLoadLimit.value);
    
    people.value = slicedActors.map(p => ({ 
      ...p, 
      NewRole: p.Role || '',
      status: 'unchanged', // 'unchanged', 'changed', 'ignored'
    }));
    
    nextTick(() => {
      correctionTableRef.value?.toggleAllSelection();
    });

  } catch (error) {
    ElMessage.error(`获取演员列表失败: ${error.message}`);
  } finally {
    isLoadingPeople.value = false;
  }
}

function getAvatarUrl(person) {
  if (!person.PrimaryImageTag) return '';
  const path = `Items/${person.Id}/Images/Primary?tag=${person.PrimaryImageTag}&quality=90`;
  return `${API_BASE_URL}/api/emby-image-proxy?path=${encodeURIComponent(path)}`;
}

const handleAiSelectionChange = (selection) => {
  selectionForAi.value = selection;
};

async function handleAiSuggest() {
  if (selectionForAi.value.length === 0) {
    ElMessage.warning('请至少勾选一位演员后再请求AI建议。');
    return;
  }
  isSuggesting.value = true;
  try {
    const actorsToProcess = selectionForAi.value;
    const actorNames = actorsToProcess.map(p => p.Name);

    const response = await fetch(`${API_BASE_URL}/api/actor-localizer/suggest-roles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: selectedMedia.value.Id,
        actor_names: actorNames,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'AI建议失败');

    let updatedCount = 0;
    actorsToProcess.forEach(personInSelection => {
      if (data[personInSelection.Name]) {
        const targetPersonInTable = people.value.find(p => p.Id === personInSelection.Id);
        if (targetPersonInTable) {
          targetPersonInTable.NewRole = data[personInSelection.Name];
          updatedCount++;
        }
      }
    });
    ElMessage.success(`AI填充完成！共更新 ${updatedCount} 条角色建议。`);

  } catch (error) {
    ElMessage.error(`AI建议失败: ${error.message}`);
  } finally {
    isSuggesting.value = false;
  }
}

async function handleApplyToEmby() {
  const changesToApply = people.value.filter(p => p.status === 'changed');
  if (changesToApply.length === 0) {
    ElMessage.info('没有状态为“已更改”的项目需要应用。');
    return;
  }

  isApplying.value = true;
  try {
    const fullPeopleResponse = await fetch(`${API_BASE_URL}/api/actor-localizer/media/${selectedMedia.value.Id}/people`);
    if (!fullPeopleResponse.ok) throw new Error('无法获取完整的演职员列表以进行更新');
    let fullPeopleList = await fullPeopleResponse.json();

    const roleUpdateMap = new Map(changesToApply.map(p => [p.Id, p.NewRole]));

    fullPeopleList.forEach(person => {
      if (person.Type === 'Actor' && roleUpdateMap.has(person.Id)) {
        person.Role = roleUpdateMap.get(person.Id);
      }
    });

    const response = await fetch(`${API_BASE_URL}/api/actor-localizer/update-roles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: selectedMedia.value.Id,
        people: fullPeopleList,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '应用失败');
    
    ElMessage.success(data.message);
    emit('update:visible', false);

  } catch (error) {
    ElMessage.error(`应用到Emby失败: ${error.message}`);
  } finally {
    isApplying.value = false;
  }
}

const getStatusInfo = (row) => {
  switch (row.status) {
    case 'changed':
      return { text: '已更改', type: 'success', effect: 'light', clickable: true };
    case 'ignored':
      return { text: '已忽略', type: 'warning', effect: 'light', clickable: true };
    default: // unchanged
      return { text: '未更改', type: 'info', effect: 'plain', clickable: false };
  }
};

const toggleStatus = (row) => {
  if (row.status === 'changed') {
    row.status = 'ignored';
  } else if (row.status === 'ignored') {
    row.status = 'changed';
  }
  // 'unchanged' 状态不可点击，所以无需处理
};
</script>

<style scoped>
.correction-dialog :deep(.el-dialog__body) {
  padding: 10px 20px 20px 20px;
}
.dialog-layout {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 20px;
  height: 75vh;
}
.step-panel {
  display: flex;
  flex-direction: column;
  gap: 15px;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 15px;
}
.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.step-number {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background-color: #609e95;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
}
.step-header h4 {
  margin: 0;
  font-size: 1.1rem;
}
.search-form {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.search-results-table {
  flex-grow: 1;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  overflow: hidden;
}
.correction-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.correction-table-container {
  flex-grow: 1;
  overflow: hidden;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
}
.actor-limit-control {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
</style>