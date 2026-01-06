<!-- frontend/src/views/ActorGalleryView.vue (完整文件覆盖) -->
<template>
  <div class="actor-gallery-page">
    <div 
      class="page-layout" 
      :class="{ 
        'left-panel-collapsed': isLeftPanelCollapsed,
        'has-backdrop': selectedMediaItem?.backdropUrl 
      }"
      :style="pageStyle"
    >
      <!-- 左侧面板 (Naive UI 重构) -->
      <div class="left-panel">
        <n-card :bordered="false" shadow="never" class="control-card-naive">
          <template #header>
            <div class="card-header">
              <span>媒体浏览器</span>
            </div>
          </template>
          <n-select
            v-model:value="selectedLibraryId"
            placeholder="请选择媒体库"
            :options="libraryOptions"
            filterable
            :loading="mediaStore.isLoading"
          />
          <n-input-group style="margin-top: 15px;">
            <n-button 
              @click="toggleSearchMode"
              :title="isGlobalSearchActive ? '切换为本地过滤' : '切换为全局搜索'"
            >
              <template #icon>
                <el-icon><component :is="isGlobalSearchActive ? Search : Filter" /></el-icon>
              </template>
            </n-button>
            <n-input
              v-model:value="searchQuery"
              :placeholder="isGlobalSearchActive ? '全局搜索标题后按回车...' : '按标题实时过滤...'"
              clearable
              @keyup.enter="handleSearch"
            />
          </n-input-group>
        </n-card>

        <n-card :bordered="false" shadow="never" class="media-list-card-naive" content-style="padding: 0; height: 100%;">
          <div v-if="(galleryStore.isLoadingItems && galleryStore.mediaItems.length === 0) || galleryStore.isSearchingGlobally" class="table-skeleton-wrapper">
            <el-skeleton :rows="10" animated />
          </div>
          <n-data-table
            v-else
            :columns="columns"
            :data="tableData"
            :row-key="row => row.Id"
            flex-height
            virtual-scroll
            :row-props="onRowProps"
            :bordered="false"
            :row-class-name="rowClassName"
            style="height: 100%;"
            class="media-data-table"
          />
        </n-card>
      </div>

      <!-- 折叠按钮 (保持不变) -->
      <div class="left-panel-collapse-button" @click="isLeftPanelCollapsed = !isLeftPanelCollapsed">
        <el-icon>
          <ArrowLeft v-if="!isLeftPanelCollapsed" />
          <ArrowRight v-else />
        </el-icon>
      </div>

      <!-- 右侧主面板 (Element Plus, 保持不变) -->
      <div 
        class="right-panel"
        v-loading="galleryStore.isUploading"
        element-loading-text="正在上传图片..."
        element-loading-background="rgba(0, 0, 0, 0.7)"
        @mousemove="handleRightPanelMouseMove"
      >
        <div class="gallery-toolbar">
          <span>悬浮预览大图</span>
          <el-switch 
            v-model="isMagnifierEnabled" 
            style="margin-left: 8px;"
          />
        </div>

        <div v-if="!selectedMediaItem" class="placeholder-wrapper">
          <el-empty description="请从左侧选择一个媒体项" />
        </div>
        
        <div v-else class="right-panel-content">
          <div class="media-info-panel">
            <div 
              class="media-poster"
              @mouseenter="handlePosterMouseEnter"
              @mouseleave="handlePosterMouseLeave"
            >
              <el-image :src="selectedMediaItem.posterUrl" fit="cover" class="poster-image">
                <template #placeholder>
                  <div class="avatar-placeholder">
                    <el-icon class="is-loading" :size="24"><Loading /></el-icon>
                  </div>
                </template>
                <template #error>
                  <div class="avatar-placeholder">
                    <el-icon><PictureFilled /></el-icon>
                  </div>
                </template>
              </el-image>
            </div>
            <div class="media-details">
              <div class="media-title-container">
                <h1 class="media-title">{{ selectedMediaItem.Name }}</h1>
                <el-button 
                  type="primary"
                  plain
                  size="small"
                  :icon="Picture" 
                  @click="openTmdbImageDialog"
                >
                  修改图片
                </el-button>
              </div>
              <div class="media-meta">
                <span v-if="selectedMediaItem.ProductionYear">{{ selectedMediaItem.ProductionYear }}</span>
                <el-divider direction="vertical" v-if="selectedMediaItem.OfficialRating" />
                <span v-if="selectedMediaItem.OfficialRating" class="rating-badge">{{ selectedMediaItem.OfficialRating }}</span>
                <el-divider direction="vertical" v-if="selectedMediaItem.CommunityRating" />
                <span v-if="selectedMediaItem.CommunityRating" class="community-rating">
                  <el-icon><StarFilled /></el-icon> {{ selectedMediaItem.CommunityRating.toFixed(1) }}
                </span>
              </div>
              <div class="media-genres">
                <el-tag v-for="genre in selectedMediaItem.Genres" :key="genre" type="info" size="small" round effect="light">
                  {{ genre }}
                </el-tag>
              </div>
              <div class="media-overview">
                <p>{{ selectedMediaItem.Overview || '暂无简介' }}</p>
              </div>
              <div v-if="selectedMediaItem.logoUrl" class="logo-container">
                <el-image :src="selectedMediaItem.logoUrl" fit="contain" class="logo-image" />
              </div>
            </div>
          </div>

          <div v-if="galleryStore.isLoadingActors" class="actor-scroll-container skeleton-container">
            <el-skeleton v-for="i in 6" :key="i" style="width: 220px;" animated>
              <template #template>
                <el-skeleton-item variant="image" style="width: 220px; height: 330px; border-radius: 8px;" />
              </template>
            </el-skeleton>
          </div>

          <div v-else-if="galleryStore.actors.length === 0" class="placeholder-wrapper actor-placeholder">
            <el-empty description="未找到该项目的演职员信息" />
          </div>
          
          <div v-else class="gallery-wrapper">
            <div v-if="showLeftScroll" class="scroll-button left" @click="scrollContent(-880)">
              <el-icon><ArrowLeftBold /></el-icon>
            </div>
            <div v-if="showRightScroll" class="scroll-button right" @click="scrollContent(880)">
              <el-icon><ArrowRightBold /></el-icon>
            </div>

            <div 
              class="actor-scroll-container" 
              ref="actorContainerRef" 
              @scroll="updateScrollButtons"
              @mousemove="handleActorContainerMouseMove"
              @mouseleave="handleActorContainerMouseLeave"
            >
              <div 
                v-for="(actor, index) in galleryStore.actors" 
                :key="actor.Id" 
                class="actor-card" 
                :ref="el => actorCardRefs[index] = el"
                :data-actor-id="actor.Id"
              >
                <el-image :src="actor.avatarUrl" fit="cover" class="actor-avatar" lazy>
                  <template #placeholder>
                    <div class="avatar-placeholder">
                      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
                    </div>
                  </template>
                  <template #error>
                    <div class="avatar-placeholder">
                      <el-icon><UserFilled /></el-icon>
                    </div>
                  </template>
                </el-image>
                
                <div class="actor-info-overlay">
                  <div class="actor-name">{{ actor.Name }}</div>
                  <div class="actor-role">{{ actor.Role }}</div>
                </div>

                <div class="actor-actions-overlay">
                  <el-dropdown
                    trigger="click"
                    @command="command => handleAvatarMenuCommand(command, actor)"
                  >
                    <el-button
                      type="primary"
                      size="small"
                      :loading="galleryStore.isUploading || (galleryStore.isFetchingTmdbActor && activeActor?.Id === actor.Id)"
                    >
                      更换头像
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="network">从网络获取 (豆瓣/TMDB)</el-dropdown-item>
                        <el-dropdown-item command="local">从本地上传</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 弹窗和工具 (Element Plus, 保持不变) -->
    <ImageMagnifier
      :visible="magnifier.visible"
      :image-url="magnifier.imageUrl"
      :position="magnifier.position"
      :size="magnifierSize"
    />
    <input type="file" ref="fileInputRef" @change="handleFileSelect" style="display: none" accept="image/*" />
    <el-dialog
      v-model="doubanDialog.visible"
      title="手动匹配豆瓣演员"
      width="500px"
      :before-close="handleDoubanDialogCancel"
    >
      <p>无法为 Emby 演员 “{{ doubanDialog.personName }}” 找到精确匹配。请从下方豆瓣演员列表中选择一个进行关联：</p>
      <el-radio-group v-model="doubanDialog.selectedActorId" class="douban-actor-list">
        <el-radio v-for="actor in doubanDialog.candidates" :key="actor.id" :label="actor.id" border>
          {{ actor.name }} <span v-if="actor.character" class="douban-role">(饰: {{ actor.character }})</span>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="handleDoubanDialogCancel">取消 (跳过豆瓣)</el-button>
        <el-button type="primary" @click="handleDoubanActorSelected" :disabled="!doubanDialog.selectedActorId">确认选择</el-button>
      </template>
    </el-dialog>
    <ImagePreviewDialog :visible="previewDialog.visible" :title="previewDialog.title" :image-url="previewDialog.imageUrl" :preview-size="previewDialog.size" @update:visible="previewDialog.visible = false" @confirm="handlePreviewConfirm"/>
    <div ref="contextMenuRef" class="context-menu" style="display: none;"><div class="menu-item" @click="handleContextMenuCommand('refresh')">刷新演员列表</div><div class="menu-item" @click="handleContextMenuCommand('poster')">用豆瓣海报更新</div></div>
    <TmdbImageManagerDialog 
      v-model:visible="isTmdbDialogVisible"
      :media-item="selectedMediaItem"
      :is-loading="galleryStore.isFetchingTmdb"
      :current-image-type="currentImageType"
      @fetch="handleFetchTmdbId"
    />
    <SingleConfirmDialog
      v-model:visible="isSingleConfirmDialogVisible"
      :candidate="galleryStore.tmdbSingleCandidate"
      @confirm="handleIdConfirm"
      @reject="handleSingleConfirmReject"
    />
    <ManualMatchDialog
      v-model:visible="isManualMatchDialogVisible"
      :candidates="galleryStore.tmdbCandidates"
      @confirm="handleIdConfirm"
    />
    <ImageSelectionDialog
      v-model:visible="isImageSelectionDialogVisible"
      :images="galleryStore.tmdbImages"
      :media-name="selectedMediaItem?.Name"
      :image-type="currentImageType"
      @confirm="handleImageSelectionConfirm"
    />
    <SingleActorConfirmDialog
      v-model:visible="isSingleActorConfirmDialogVisible"
      :context="galleryStore.tmdbSingleActorCandidate"
      @confirm="handleActorIdConfirm"
      @reject="handleSingleActorReject"
    />
    <ActorListDialog
      v-model:visible="isActorListDialogVisible"
      :candidates="galleryStore.tmdbActorCandidates"
      @confirm="handleActorIdConfirm"
      @reject="handleActorListReject"
    />
    <ActorManualMatchDialog
      v-model:visible="isActorManualMatchDialogVisible"
      :candidates="galleryStore.tmdbActorCandidates"
      @confirm="handleActorIdConfirm"
    />
    <ImageSelectionDialog
      v-model:visible="isActorImageSelectionDialogVisible"
      :images="galleryStore.tmdbActorImages"
      :media-name="activeActor?.Name"
      image-type="poster"
      @confirm="handleActorImageSelectionConfirm"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, watch, nextTick, onBeforeUpdate, reactive, h } from 'vue'
import { useMediaStore } from '@/stores/media'
import { useActorGalleryStore } from '@/stores/actorGallery'
import { useConfigStore } from '@/stores/config'
import { useStorage, useIntersectionObserver, useMouse, StorageSerializers } from '@vueuse/core'
import { UserFilled, Loading, ArrowLeftBold, ArrowRightBold, ArrowLeft, ArrowRight, PictureFilled, StarFilled, Picture, Filter, Search } from '@element-plus/icons-vue'
import { ElMessageBox, ElLoading, ElMessage } from 'element-plus'
import { NButton, NInput, NPopover, NSpace } from 'naive-ui'
import ImagePreviewDialog from '@/components/ImagePreviewDialog.vue'
import ImageMagnifier from '@/components/ImageMagnifier.vue'
import TmdbImageManagerDialog from '@/components/TmdbImageManagerDialog.vue'
import ManualMatchDialog from '@/components/ManualMatchDialog.vue'
import ImageSelectionDialog from '@/components/ImageSelectionDialog.vue'
import SingleConfirmDialog from '@/components/SingleConfirmDialog.vue'
import SingleActorConfirmDialog from '@/components/SingleActorConfirmDialog.vue'
import ActorManualMatchDialog from '@/components/ActorManualMatchDialog.vue'
import ActorListDialog from '@/components/ActorListDialog.vue'
import { API_BASE_URL } from '@/config/apiConfig';
import { TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';
import { MAGNIFIER_SIZE, MAGNIFIER_GAP } from '@/config/appConstants';

const mediaStore = useMediaStore()
const galleryStore = useActorGalleryStore()
const configStore = useConfigStore()

const isLeftPanelCollapsed = useStorage('gallery-left-panel-collapsed', true);
const isMagnifierEnabled = useStorage('gallery-magnifier-enabled', false);

const selectedMediaItemCache = useStorage('gallery-selected-media-item-cache', null, undefined, { serializer: StorageSerializers.object });
const actorsCache = useStorage('gallery-actors-cache', []);
const mediaItemsCache = useStorage('gallery-media-items-cache', [], undefined, { serializer: StorageSerializers.object });

const selectedLibraryId = useStorage('gallery-selected-library-id', null)
const selectedMediaItemId = useStorage('gallery-selected-media-id', null)

const magnifierSize = MAGNIFIER_SIZE;
const magnifierGap = MAGNIFIER_GAP;

const magnifier = reactive({ visible: false, imageUrl: '', position: { x: 0, y: 0 } });
const { x, y } = useMouse();

const currentHoveredActorId = ref(null);
const isHoveringPoster = ref(false);

const searchQuery = ref('')
const selectedMediaItem = ref(selectedMediaItemCache.value)
const actorContainerRef = ref(null)
const actorCardRefs = ref([])
const fileInputRef = ref(null)
const contextMenuRef = ref(null)
const showLeftScroll = ref(false)
const showRightScroll = ref(false)
const activeActor = ref(null)
let activeMediaItemForMenu = null
let resizeObserver = null
const doubanDialog = ref({ visible: false, personName: '', candidates: [], selectedActorId: null, })
const previewDialog = ref({ visible: false, title: '', imageUrl: '', size: { width: 300, height: 450 }, type: '', context: null, })

const isTmdbDialogVisible = ref(false)
const isManualMatchDialogVisible = ref(false)
const isImageSelectionDialogVisible = ref(false)
const isSingleConfirmDialogVisible = ref(false)
const currentImageType = ref('poster')

const newDoubanId = ref('');
const isUpdatingDoubanId = ref(false);

const isSingleActorConfirmDialogVisible = ref(false)
const isActorListDialogVisible = ref(false)
const isActorManualMatchDialogVisible = ref(false)
const isActorImageSelectionDialogVisible = ref(false)

const isGlobalSearchActive = ref(false);

const libraryOptions = computed(() => 
  mediaStore.libraries.map(lib => ({ label: lib.name, value: lib.id }))
);

const filteredMediaItems = computed(() => {
  if (!searchQuery.value) return galleryStore.mediaItems;
  return galleryStore.mediaItems.filter(item => item.Name.toLowerCase().includes(searchQuery.value.toLowerCase()));
});

const tableData = computed(() => isGlobalSearchActive.value ? galleryStore.globalSearchResults : filteredMediaItems.value);

const getDoubanId = (row) => {
  if (!row.ProviderIds) return null;
  const doubanKey = Object.keys(row.ProviderIds).find(key => key.toLowerCase() === 'douban');
  return doubanKey ? row.ProviderIds[doubanKey] : null;
};

const createColumns = () => [
  { title: '标题', key: 'Name', ellipsis: { tooltip: true } },
  { title: '年份', key: 'ProductionYear', width: 80 },
  {
    title: '豆瓣ID',
    key: 'doubanId',
    width: 120,
    render(row) {
      const popoverContent = () => h(
        'div',
        { class: 'douban-id-editor' },
        [
          h(NInput, {
            value: newDoubanId.value,
            placeholder: '请输入新的豆瓣ID',
            onUpdateValue: (val) => newDoubanId.value = val,
          }),
          h('div', { class: 'editor-actions' }, [
            h(NButton, {
              type: 'primary',
              size: 'small',
              loading: isUpdatingDoubanId.value,
              onClick: () => handleUpdateDoubanId(row),
            }, () => '确认'),
          ]),
        ]
      );

      return h(
        NPopover,
        {
          trigger: 'click',
          placement: 'right',
          onUpdateShow: () => newDoubanId.value = getDoubanId(row) || '',
        },
        {
          trigger: () => h(
            NButton,
            { text: true, type: 'primary' },
            () => getDoubanId(row) || 'N/A'
          ),
          default: popoverContent,
        }
      );
    },
  },
];

const columns = createColumns();

const onRowProps = (row) => {
  return {
    style: 'cursor: pointer;',
    onClick: () => handleMediaItemClick(row),
    onContextmenu: (e) => {
      e.preventDefault();
      handleMediaItemContextMenu(row, null, e);
    }
  };
};

const rowClassName = (row) => {
  if (row.Id === selectedMediaItemId.value) {
    return 'selected-row';
  }
  return '';
};

const processMediaItem = (item) => {
  if (!item) return null;
  const serverConfig = configStore.appConfig.server_config;
  if (!serverConfig || !serverConfig.api_key) return item;
  const buildUrl = (type, options = {}) => {
    let tag = '';
    if (type === 'Backdrop') {
      if (item.BackdropImageTags && item.BackdropImageTags.length > 0) tag = item.BackdropImageTags[0];
    } else {
      if (item.ImageTags && item.ImageTags[type]) tag = item.ImageTags[type];
    }
    if (!tag) return '';
    const params = new URLSearchParams({ api_key: serverConfig.api_key, tag: tag, ...options });
    const embyPath = `Items/${item.Id}/Images/${type}?${params.toString()}`;
    return `${API_BASE_URL}/api/emby-image-proxy?path=${encodeURIComponent(embyPath)}`;
  };
  item.posterUrl = buildUrl('Primary');
  item.backdropUrl = buildUrl('Backdrop', { maxWidth: 1920, quality: 80 });
  item.logoUrl = buildUrl('Logo');
  return item;
};

const processActorItem = (actor) => {
  if (!actor) return null;
  const serverConfig = configStore.appConfig.server_config;
  if (actor.PrimaryImageTag && serverConfig && serverConfig.api_key) {
    const params = new URLSearchParams({ api_key: serverConfig.api_key, tag: actor.PrimaryImageTag, maxWidth: 1000, quality: 90 });
    const embyPath = `Items/${actor.Id}/Images/Primary?${params.toString()}`;
    actor.avatarUrl = `${API_BASE_URL}/api/emby-image-proxy?path=${encodeURIComponent(embyPath)}`;
  }
  return actor;
}

onMounted(async () => {
  await configStore.fetchConfig();
  if (selectedMediaItemCache.value) selectedMediaItem.value = processMediaItem(selectedMediaItemCache.value);
  if (actorsCache.value?.length > 0) galleryStore.actors = actorsCache.value.map(actor => processActorItem(actor));
  mediaStore.fetchLibraries();
  if (selectedLibraryId.value) galleryStore.fetchLibraryItems(selectedLibraryId.value, true);
  document.body.addEventListener('click', () => { if (contextMenuRef.value) contextMenuRef.value.style.display = 'none' });
});

watch(() => galleryStore.mediaItems, (newItems) => {
  if (newItems?.length > 0) {
    mediaItemsCache.value = newItems;
    if (selectedMediaItemId.value) {
      const itemToHighlight = newItems.find(i => i.Id === selectedMediaItemId.value);
      if (itemToHighlight) {
        configStore.fetchConfig().then(() => {
          const fullItem = processMediaItem(itemToHighlight);
          selectedMediaItem.value = fullItem;
          selectedMediaItemCache.value = fullItem;
        });
      }
    }
  }
}, { deep: true });

onUnmounted(() => { if (resizeObserver) resizeObserver.disconnect() })
onBeforeUpdate(() => { actorCardRefs.value = [] })
const easeInOutQuad = t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
const smoothScrollBy = (element, distance) => { if (!element) return; const duration = 500; const startScrollLeft = element.scrollLeft; let startTime = null; const animationStep = (currentTime) => { if (!startTime) startTime = currentTime; const elapsed = currentTime - startTime; const progress = Math.min(elapsed / duration, 1); const easedProgress = easeInOutQuad(progress); element.scrollLeft = startScrollLeft + distance * easedProgress; if (progress < 1) requestAnimationFrame(animationStep); }; requestAnimationFrame(animationStep); };
const scrollContent = (amount) => smoothScrollBy(actorContainerRef.value, amount);
const updateScrollButtons = () => { const el = actorContainerRef.value; if (!el) return; showLeftScroll.value = el.scrollLeft > 0; showRightScroll.value = el.scrollWidth > el.clientWidth && Math.ceil(el.scrollLeft) < el.scrollWidth - el.clientWidth; }
const handleActorContainerMouseMove = (event) => { currentHoveredActorId.value = event.target.closest('.actor-card')?.dataset.actorId || null; };
const handleActorContainerMouseLeave = () => { currentHoveredActorId.value = null; };
const handlePosterMouseEnter = () => { isHoveringPoster.value = true; };
const handlePosterMouseLeave = () => { isHoveringPoster.value = false; };
const handleRightPanelMouseMove = () => {
  if (!magnifier.visible) return;
  if (isHoveringPoster.value) {
    magnifier.position.x = x.value + magnifierGap;
    magnifier.position.y = y.value + magnifierGap;
  } else {
    magnifier.position.x = x.value - magnifierSize.width - magnifierGap;
    magnifier.position.y = y.value - magnifierSize.height - magnifierGap;
  }
};

watch([isHoveringPoster, currentHoveredActorId, isMagnifierEnabled], ([posterHover, actorId, enabled]) => {
  if (!enabled) { magnifier.visible = false; return; }
  if (posterHover && selectedMediaItem.value?.posterUrl) {
    magnifier.imageUrl = selectedMediaItem.value.posterUrl;
    magnifier.visible = true;
  } else if (actorId) {
    const actor = galleryStore.actors.find(a => a.Id === actorId);
    if (actor?.avatarUrl) {
      magnifier.imageUrl = actor.avatarUrl;
      magnifier.visible = true;
    } else {
      magnifier.visible = false;
    }
  } else {
    magnifier.visible = false;
  }
});

watch(() => galleryStore.actors, (newActors) => { 
  if (newActors?.length > 0) { 
    actorsCache.value = newActors;
    nextTick(() => { 
      actorCardRefs.value.forEach((cardEl, index) => { 
        if (cardEl) useIntersectionObserver(cardEl, ([{ isIntersecting }]) => { if (isIntersecting && !galleryStore.actors[index].avatarUrl) processActorItem(galleryStore.actors[index]); }) 
      }); 
      updateScrollButtons(); 
      if (actorContainerRef.value) { 
        if (resizeObserver) resizeObserver.disconnect(); 
        resizeObserver = new ResizeObserver(updateScrollButtons); 
        resizeObserver.observe(actorContainerRef.value) 
      } 
    }) 
  } else { 
    showLeftScroll.value = false; 
    showRightScroll.value = false; 
  } 
}, { deep: true })

watch(selectedLibraryId, (libraryId) => {
  isGlobalSearchActive.value = false;
  galleryStore.clearGlobalSearch();
  searchQuery.value = '';
  selectedMediaItem.value = null; 
  selectedMediaItemId.value = null;
  selectedMediaItemCache.value = null;
  galleryStore.actors = [];
  actorsCache.value = [];
  galleryStore.fetchLibraryItems(libraryId);
});

const handleMediaItemClick = async (row) => { 
  if (selectedMediaItem.value?.Id === row.Id) return; 
  await configStore.fetchConfig();
  const fullItem = processMediaItem(row);
  selectedMediaItem.value = fullItem;
  selectedMediaItemId.value = row.Id;
  selectedMediaItemCache.value = fullItem;
  galleryStore.fetchItemActors(row.Id);
}

const handleMediaItemContextMenu = (row, column, event) => { activeMediaItemForMenu = row; const menu = contextMenuRef.value; menu.style.display = 'block'; menu.style.left = `${event.clientX}px`; menu.style.top = `${event.clientY}px` }
const handleContextMenuCommand = async (command) => {
  contextMenuRef.value.style.display = 'none';
  if (!activeMediaItemForMenu) return;
  if (command === 'refresh') galleryStore.fetchItemActors(activeMediaItemForMenu.Id);
  else if (command === 'poster') ElMessage.info('此功能已整合到“修改图片”中。');
};

const handleAvatarMenuCommand = (command, actor) => {
  activeActor.value = actor;
  if (command === 'network') {
    runAvatarFlow(actor, selectedMediaItem.value);
  } else if (command === 'local') {
    fileInputRef.value.click();
  }
};

const runAvatarFlow = async (actor, mediaItem) => {
  const loadingInstance = ElLoading.service({ lock: true, text: '正在获取数据...', background: 'rgba(0, 0, 0, 0.7)' });
  try {
    let result;
    if (actor && mediaItem) {
      result = await galleryStore.startAndFetchAvatarFlow(actor, mediaItem);
    } else {
      result = await galleryStore.fetchAvatarFlow();
    }

    if (!result) {
      ElMessage.error('流程中止，未能从后端获取有效响应。');
      return;
    }
    
    if (result.status === 'success') {
      isActorImageSelectionDialogVisible.value = true;
    } else if (result.status === 'douban_manual_selection') {
      doubanDialog.value = {
        visible: true,
        personName: activeActor.value.Name,
        candidates: result.intervention_details.candidates,
        selectedActorId: null,
      };
    } else if (result.status.startsWith('tmdb_')) {
      const details = result.intervention_details;
      if (details.status === 'single_actor_confirm') {
        isSingleActorConfirmDialogVisible.value = true;
      } else if (details.status === 'context_manual_selection') {
        isActorListDialogVisible.value = true;
      } else if (details.status === 'manual_actor_selection') {
        isActorManualMatchDialogVisible.value = true;
      }
    } else if (result.status === 'all_failed') {
      ElMessage.error('所有数据源均未找到可用头像。');
    }

  } finally {
    loadingInstance.close();
  }
};

const handleFileSelect = (event) => { const file = event.target.files[0]; if (file) { const imageUrl = URL.createObjectURL(file); previewDialog.value = { visible: true, title: `为 “${activeActor.value.Name}” 更新头像`, imageUrl: imageUrl, size: { width: 250, height: 250 }, type: 'avatar_local', context: { personId: activeActor.value.Id, file: file } }; } event.target.value = '' }

const handleDoubanActorSelected = async () => {
  const selected = doubanDialog.value.candidates.find(c => c.id === doubanDialog.value.selectedActorId);
  doubanDialog.value.visible = false;
  galleryStore.updateAvatarFlowState({ confirmed_douban_actor: selected });
  await runAvatarFlow();
};

const handleDoubanDialogCancel = async () => {
  doubanDialog.value.visible = false;
  ElMessage.info('已跳过豆瓣源，将继续从 TMDB 获取头像。');
  galleryStore.updateAvatarFlowState({ skip_douban: true });
  await runAvatarFlow();
};

const handleActorIdConfirm = async (tmdbPersonId) => {
  isSingleActorConfirmDialogVisible.value = false;
  isActorListDialogVisible.value = false;
  isActorManualMatchDialogVisible.value = false;
  galleryStore.updateAvatarFlowState({ confirmed_tmdb_person_id: tmdbPersonId, force_tmdb_global_search: false, force_tmdb_context_list: false });
  ElMessage.success('演员ID已确认，正在获取图片并执行后台关联...');
  await runAvatarFlow();
};

const handleSingleActorReject = async () => {
  galleryStore.updateAvatarFlowState({ force_tmdb_context_list: true, confirmed_tmdb_person_id: null });
  isSingleActorConfirmDialogVisible.value = false;
  await runAvatarFlow();
};

const handleActorListReject = async () => {
  galleryStore.updateAvatarFlowState({ force_tmdb_global_search: true });
  isActorListDialogVisible.value = false;
  await runAvatarFlow();
};

const handlePreviewConfirm = async () => {
  const { type, context, title } = previewDialog.value;
  try {
    await ElMessageBox.confirm('此操作将直接修改您 Emby 媒体库中的源文件，且操作不可逆。是否确定要继续？', `确认操作: ${title}`, { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' });
    previewDialog.value.visible = false;
    let success = false;
    if (type === 'avatar_local') {
      success = await galleryStore.uploadAvatarFromLocal(context.personId, context.file);
      if (success) setTimeout(() => refreshActorAvatar(context.personId), 3000);
    }
  } catch (error) { console.log('Upload cancelled by user.'); }
};

const refreshActorAvatar = (personId) => {
  const actor = galleryStore.actors.find(a => a.Id === personId);
  if (actor) {
    const newActor = processActorItem(actor);
    actor.avatarUrl = `${newActor.avatarUrl}&t=${Date.now()}`;
  }
};

const pageStyle = computed(() => selectedMediaItem.value?.backdropUrl ? { '--backdrop-image-url': `url(${selectedMediaItem.value.backdropUrl})` } : {});

const openTmdbImageDialog = () => { isTmdbDialogVisible.value = true; }

const handleFetchTmdbId = async (imageType) => {
  currentImageType.value = imageType;
  const payload = { item_id: selectedMediaItem.value.Id, image_type: imageType };
  
  if (imageType === 'poster') {
    const status = await galleryStore.fetchCombinedPosters(selectedMediaItem.value.Id);
    if (status === 'success') {
      isImageSelectionDialogVisible.value = true;
    } else {
      const fallbackStatus = await galleryStore.fetchTmdbIdFlow(payload);
      if (fallbackStatus === 'manual_selection') isManualMatchDialogVisible.value = true;
      else if (fallbackStatus === 'single_candidate_confirm') isSingleConfirmDialogVisible.value = true;
    }
  } else {
    const status = await galleryStore.fetchTmdbIdFlow(payload);
    if (status === 'success') isImageSelectionDialogVisible.value = true;
    else if (status === 'manual_selection') isManualMatchDialogVisible.value = true;
    else if (status === 'single_candidate_confirm') isSingleConfirmDialogVisible.value = true;
  }
};

const handleIdConfirm = async (tmdbId) => {
  isManualMatchDialogVisible.value = false;
  isSingleConfirmDialogVisible.value = false;
  const payload = { item_id: selectedMediaItem.value.Id, tmdb_id: tmdbId, image_type: currentImageType.value };
  const status = await galleryStore.confirmTmdbIdAndFetchImages(payload);
  if (status === 'success') {
    isImageSelectionDialogVisible.value = true;
  }
};

const handleSingleConfirmReject = () => { isSingleConfirmDialogVisible.value = false; isManualMatchDialogVisible.value = true; };

const handleImageSelectionConfirm = async (image) => {
  try {
    await ElMessageBox.confirm('此操作将直接替换 Emby 中的图片，且无法撤销。确定要继续吗？', '最终确认', { confirmButtonText: '确定更换', cancelButtonText: '取消', type: 'warning' });
    isTmdbDialogVisible.value = false;
    isImageSelectionDialogVisible.value = false;
    let imageUrl = image.source === 'douban' ? image.file_path : `${TMDB_IMAGE_BASE_URL}${TMDB_IMAGE_SIZES.original}${image.file_path}`;
    let success = false;
    if (currentImageType.value === 'poster') success = await galleryStore.uploadPosterFromUrl(selectedMediaItem.value.Id, imageUrl, image.source);
    else if (currentImageType.value === 'backdrop') success = await galleryStore.uploadBackdropFromUrl(selectedMediaItem.value.Id, imageUrl);
    else if (currentImageType.value === 'logo') success = await galleryStore.uploadLogoFromUrl(selectedMediaItem.value.Id, imageUrl);
    if (success) {
      setTimeout(() => {
        const refreshedItem = processMediaItem(selectedMediaItem.value);
        selectedMediaItem.value.posterUrl = `${refreshedItem.posterUrl}&t=${Date.now()}`;
        selectedMediaItem.value.backdropUrl = `${refreshedItem.backdropUrl}&t=${Date.now()}`;
        selectedMediaItem.value.logoUrl = `${refreshedItem.logoUrl}&t=${Date.now()}`;
      }, 3000);
    }
  } catch (error) { console.log('Upload cancelled by user.'); }
};

const handleActorImageSelectionConfirm = async (image) => {
  let newNameForUpdate = null;
  const embyName = activeActor.value.Name;
  const newName = image.actor_name;
  if (newName && embyName !== newName) {
    try {
      const result = await ElMessageBox.confirm(`您选择的演员名称与 Emby 中的不一致。<br/>- Emby 名称: <strong>${embyName}</strong><br/>- 新名称: <strong>${newName}</strong><br/><br/>此操作将全局更新该演员的姓名。是否要同步更新？`, '确认名称变更', { confirmButtonText: '更新姓名并上传头像', cancelButtonText: '仅上传头像', distinguishCancelAndClose: true, type: 'warning', dangerouslyUseHTMLString: true });
      if (result === 'confirm') newNameForUpdate = newName;
    } catch (action) { if (action === 'close') { ElMessage.info('操作已取消'); return; } }
  }
  try {
    await ElMessageBox.confirm(`确定要为演员 “${embyName}” 更换这个头像吗？`, '最终确认', { confirmButtonText: '确定更换', cancelButtonText: '取消', type: 'info' });
    isActorImageSelectionDialogVisible.value = false;
    const success = await galleryStore.uploadAvatar(activeActor.value.Id, image, newNameForUpdate);
    if (success) {
      setTimeout(() => {
        refreshActorAvatar(activeActor.value.Id);
        if (newNameForUpdate) galleryStore.fetchItemActors(selectedMediaItem.value.Id);
      }, 3000);
    }
  } catch (error) { console.log('Upload cancelled by user.'); }
};

const handleUpdateDoubanId = async (row) => {
  if (!newDoubanId.value || !/^\d+$/.test(newDoubanId.value)) { ElMessage.warning('请输入有效的纯数字豆瓣ID。'); return; }
  isUpdatingDoubanId.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/gallery/items/${row.Id}/update-douban-id`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ douban_id: newDoubanId.value }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '更新失败');
    ElMessage.success(data.message || '豆瓣ID更新成功！');
    row.ProviderIds.Douban = newDoubanId.value;
    if (selectedMediaItem.value?.Id === row.Id) selectedMediaItem.value.ProviderIds.Douban = newDoubanId.value;
  } catch (error) {
    ElMessage.error(`更新豆瓣ID失败: ${error.message}`);
  } finally {
    isUpdatingDoubanId.value = false;
  }
};

const toggleSearchMode = () => { isGlobalSearchActive.value = !isGlobalSearchActive.value; if (!isGlobalSearchActive.value) galleryStore.clearGlobalSearch(); };
const handleSearch = () => { if (isGlobalSearchActive.value) galleryStore.searchAllMedia(searchQuery.value); };
</script>

<style scoped>
.control-card-naive,
.media-list-card-naive {
  flex-shrink: 0;
  background-color: var(--el-bg-color-overlay);
}
.media-list-card-naive {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
}

/* --- 核心修改：直接覆盖表格单元格和表头的背景色 --- */
.media-data-table {
  /* 策略1：通过覆盖 Naive UI 的 CSS 变量来改变颜色 */
  --n-th-color: var(--el-bg-color-overlay) !important;
  --n-td-color: var(--el-bg-color-overlay) !important;
  --n-td-color-hover: var(--el-fill-color-light) !important;
  height: 100%;
}

/* 策略2：使用深度选择器作为双重保险，强制修改 DOM 元素背景 */
.media-data-table :deep(.n-data-table-th),
.media-data-table :deep(.n-data-table-td) {
  background-color: var(--el-bg-color-overlay) !important;
}

.media-data-table :deep(.n-data-table-tr) {
  cursor: pointer;
}

.media-data-table :deep(.n-data-table-tr.selected-row .n-data-table-td) {
  background-color: var(--el-color-primary-light-9) !important;
}
.douban-id-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.editor-actions {
  text-align: right;
}

.actor-gallery-page {
  height: 100%;
  overflow: hidden;
}
.page-layout {
  display: flex;
  height: 100%;
  position: relative;
  gap: 0;
}
.left-panel {
  width: 400px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1), margin-right 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  margin-right: 20px;
}
.page-layout.left-panel-collapsed .left-panel {
  width: 0;
  margin-right: 0;
}
.right-panel {
  flex-grow: 1;
  overflow: hidden;
  border: none;
  border-left: 1px solid var(--el-border-color-light);
  border-radius: 0;
  position: relative;
  display: flex;
  flex-direction: column;
}
.left-panel-collapse-button {
  position: absolute;
  top: 50%;
  left: 400px;
  transform: translateY(-50%);
  z-index: 10;
  width: 24px;
  height: 48px;
  border-radius: 0 6px 6px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  background-color: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color);
  border-left: none;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
.left-panel-collapse-button:hover {
  background-color: var(--el-fill-color-light);
  color: var(--el-color-primary);
}
.left-panel-collapse-button .el-icon {
  font-size: 16px;
}
.page-layout.left-panel-collapsed .left-panel-collapse-button {
  left: 0px;
  border-radius: 0 6px 6px 0;
}

.gallery-toolbar {
  position: absolute;
  top: -10px;
  right: 40px;
  z-index: 5;
  display: flex;
  align-items: center;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  padding: 10px 0;
}

.table-skeleton-wrapper {
  padding: 20px;
  height: 100%;
  box-sizing: border-box;
}
.placeholder-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
.placeholder-wrapper.actor-placeholder {
  flex-grow: 1;
}

.right-panel-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.media-info-panel {
  flex-shrink: 0;
  display: flex;
  gap: 30px;
  padding: 20px;
  height: 460px;
  box-sizing: border-box;
  border-bottom: 1px solid var(--el-border-color-light);
}
.media-poster {
  width: 280px;
  height: 420px;
  flex-shrink: 0;
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--el-fill-color-light);
  transition: transform 0.3s cubic-bezier(0.25, 0.8, 0.25, 1), box-shadow 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  cursor: pointer;
  position: relative;
}
.media-poster:hover {
  transform: scale(1.03);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.25), 0 10px 10px rgba(0, 0, 0, 0.22);
}
.poster-image {
  width: 100%;
  height: 100%;
}
.media-details {
  flex-grow: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.media-title-container {
  display: flex;
  align-items: flex-end;
  gap: 15px;
  margin-bottom: 10px;
}
.media-title {
  margin: 0;
  font-size: 1.8rem;
  font-weight: bold;
  color: var(--el-text-color-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.2;
}
.media-title-container .el-button {
  flex-shrink: 0;
  margin-bottom: 4px;
}

.media-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 15px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.rating-badge {
  border: 1px solid var(--el-border-color);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.community-rating {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #E6A23C;
}
.media-genres {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 15px;
}
.media-overview {
  flex-grow: 0;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  padding-right: 10px;
}
.media-overview p {
  margin: 0;
}

.logo-container {
  margin-top: 30px;
  text-align: left;
  display: flex;
  align-items: center;
}
.logo-image {
  width: 100%;
  height: auto;
  max-width: 300px;
  filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
}

.gallery-wrapper {
  position: relative;
  flex-grow: 1;
  width: 100%;
  overflow: hidden;
}
.scroll-button {
  position: absolute;
  bottom: 165px;
  transform: translateY(-50%);
  z-index: 20;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background-color: rgba(30, 30, 30, 0.6);
  color: white;
  display: flex;
  justify-content: center;
  align-items: center;
  cursor: pointer;
  transition: all 0.2s ease-in-out;
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.scroll-button:hover {
  background-color: rgba(0, 0, 0, 0.8);
  transform: translateY(-50%) scale(1.1);
}
.scroll-button.left {
  left: 15px;
}
.scroll-button.right {
  right: 15px;
}
.scroll-button .el-icon {
  font-size: 24px;
}

.actor-scroll-container {
  height: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
  padding: 20px;
  box-sizing: border-box;
  display: flex;
  align-items: flex-end;
  gap: 20px;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.actor-scroll-container::-webkit-scrollbar {
  display: none;
}

.skeleton-container {
  display: flex;
  align-items: flex-end;
  gap: 20px;
}

.actor-card {
  position: relative;
  width: 220px;
  height: 330px;
  flex-shrink: 0;
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--el-fill-color-light);
  transition: transform 0.2s ease-in-out;
}
.actor-card:hover {
  transform: scale(1.03);
  box-shadow: 0 8px 20px rgba(0,0,0,0.3);
}

.actor-avatar {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.actor-avatar :deep(img) {
  object-fit: cover;
}
.actor-avatar:deep(img:focus-visible),
.actor-avatar:deep(.el-image__inner:focus-visible) {
  outline: none !important;
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
}
.avatar-placeholder .el-icon {
  font-size: 48px;
}

.actor-info-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 15px;
  color: #fff;
  text-align: center;
  background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.7) 50%, transparent 100%);
  z-index: 1;
  pointer-events: none;
  transition: opacity 0.2s ease-in-out;
}
.actor-card:hover .actor-info-overlay {
  opacity: 0;
}

.actor-name {
  font-weight: bold;
  font-size: 0.9rem;
  margin-bottom: 4px;
  text-shadow: 1px 1px 3px rgba(0,0,0,0.7);
}
.actor-role {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.8);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%; 
  text-shadow: 1px 1px 2px rgba(0,0,0,0.7);
}

.actor-actions-overlay,
.poster-actions-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 2;
  opacity: 0;
  transform: translateY(10px);
  transition: opacity 0.2s ease-in-out, transform 0.2s ease-in-out;
  pointer-events: none;
  display: flex;
  justify-content: center;
  align-items: flex-end;
  height: 100%;
  padding: 15px;
}

.actor-card:hover .actor-actions-overlay,
.media-poster:hover .poster-actions-overlay {
  opacity: 1;
  transform: translateY(0);
}

.actor-actions-overlay .el-button,
.poster-actions-overlay .el-button {
  width: 100%;
  --el-button-bg-color: rgba(60, 60, 60, 0.7);
  --el-button-border-color: rgba(255, 255, 255, 0.2);
  --el-button-hover-bg-color: rgba(80, 80, 80, 0.8);
  --el-button-hover-border-color: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(4px);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  pointer-events: auto;
}
.actor-actions-overlay .el-dropdown {
  width: 100%;
  pointer-events: auto;
}

.douban-actor-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 40vh;
  overflow-y: auto;
  padding: 5px;
}

.douban-actor-list .el-radio {
  width: 100%;
  height: auto;
  margin: 0 !important;
  padding: 10px 15px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  display: flex;
  align-items: center;
  box-sizing: border-box;
  transition: border-color 0.2s, background-color 0.2s;
}

.douban-actor-list .el-radio:hover {
  border-color: var(--el-color-primary-light-5);
  background-color: var(--el-color-primary-light-9);
}

.douban-actor-list .el-radio.is-checked {
  border-color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}

.douban-actor-list .el-radio :deep(.el-radio__label) {
  flex-grow: 1;
  padding-left: 10px;
  white-space: normal;
  line-height: 1.5;
  color: var(--el-text-color-regular);
}

.douban-actor-list .el-radio.is-checked :deep(.el-radio__label) {
  color: var(--el-color-primary);
}

.douban-role {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.context-menu {
  position: fixed;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  box-shadow: var(--el-box-shadow-light);
  padding: 5px 0;
  z-index: 3000;
  min-width: 150px;
}
.menu-item {
  padding: 8px 15px;
  cursor: pointer;
}
.menu-item:hover {
  background-color: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.gallery-toolbar :deep(.el-switch.is-checked .el-switch__core) {
  background-color: #609e95;
  border-color: #609e9e;
}

.page-layout {
  position: relative;
}

.page-layout::before,
.page-layout::after {
  content: '';
  position: absolute;
  top: -20px;
  left: 0;
  right: -20px;
  bottom: -20px;
  opacity: 0;
  transition: opacity 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}

.page-layout::before {
  background-image: var(--backdrop-image-url);
  background-size: cover;
  background-position: center;
  z-index: -2;
}

.page-layout::after {
  background-color: rgba(0, 0, 0, 0.6);
  z-index: -1;
}

.page-layout.has-backdrop::before,
.page-layout.has-backdrop::after {
  opacity: 1;
}

.left-panel {
  position: relative;
  z-index: 2;
  background-color: var(--el-bg-color);
}

.right-panel {
  position: relative;
  z-index: 1;
}

.page-layout.has-backdrop .right-panel,
.page-layout.has-backdrop .right-panel-content,
.page-layout.has-backdrop .placeholder-wrapper,
.page-layout.has-backdrop .media-info-panel,
.page-layout.has-backdrop .gallery-wrapper,
.page-layout.has-backdrop .actor-scroll-container {
  background-color: transparent;
}

.page-layout.has-backdrop .media-title {
  color: #fff;
  text-shadow: 0 2px 4px rgba(0,0,0,0.5);
}
.page-layout.has-backdrop .media-meta {
  color: #e0e0e0;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}
.page-layout.has-backdrop .media-overview {
  color: #dcdcdc;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}
.page-layout.has-backdrop .media-info-panel {
  border-bottom-color: rgba(255, 255, 255, 0.2);
}
.page-layout.has-backdrop .el-divider--vertical {
  border-color: rgba(255, 255, 255, 0.3);
}
.page-layout.has-backdrop .rating-badge {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.5);
  background-color: rgba(0,0,0,0.2);
}
.page-layout.has-backdrop .community-rating {
  color: #ffc107;
}
.page-layout.has-backdrop .gallery-toolbar {
  color: #fff;
  text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}

.page-layout.has-backdrop .media-title-container .el-button {
  --el-button-text-color: #e0e0e0;
  --el-button-bg-color: rgba(255, 255, 255, 0.1);
  --el-button-border-color: rgba(255, 255, 255, 0.25);
  --el-button-hover-text-color: #ffffff;
  --el-button-hover-bg-color: rgba(255, 255, 255, 0.2);
  --el-button-hover-border-color: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(4px);
}
</style>