// frontend/stores/actorGallery.js (修改后)
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import { API_BASE_URL, TMDB_IMAGE_BASE_URL, TMDB_IMAGE_SIZES } from '@/config/apiConfig';

export const useActorGalleryStore = defineStore('actorGallery', () => {
  const isLoadingItems = ref(false)
  const isLoadingActors = ref(false)
  const isUploading = ref(false)

  const mediaItems = ref([])
  const actors = ref([])

  const isSearchingGlobally = ref(false)
  const globalSearchResults = ref([])

  const isFetchingTmdb = ref(false)
  const tmdbCandidates = ref([])
  const tmdbImages = ref([])
  const tmdbSingleCandidate = ref(null)

  const isFetchingTmdbActor = ref(false)
  const tmdbActorCandidates = ref([])
  const tmdbSingleActorCandidate = ref(null)
  const tmdbActorImages = ref([])

  const avatarFlowState = ref({});

  const showMessage = (type, message) => {
    ElMessage({ message, type, showClose: true, duration: 3000 })
  }

  // --- 核心修改 1：合并 start 和 fetch 方法 ---
  const startAndFetchAvatarFlow = async (actor, mediaItem) => {
    // 步骤1: 初始化或重置流程状态
    avatarFlowState.value = {
      emby_person_id: actor.Id,
      emby_person_name: actor.Name,
      emby_media_item_id: mediaItem.Id,
    };
    // 清理旧的候选列表
    tmdbActorCandidates.value = [];
    tmdbSingleActorCandidate.value = null;
    tmdbActorImages.value = [];

    // 步骤2: 直接调用内部的 fetch 逻辑
    return await fetchAvatarFlow();
  };

  const updateAvatarFlowState = (updates) => {
    avatarFlowState.value = { ...avatarFlowState.value, ...updates };
    console.log('➡️ [调试-Store] 步骤2: Pinia状态已更新。当前 avatarFlowState:', JSON.parse(JSON.stringify(avatarFlowState.value)));
  };

  // frontend/stores/actorGallery.js (函数替换)

  async function fetchAvatarFlow() {
    const personId = avatarFlowState.value.emby_person_id;
    if (!personId) {
      const errorMsg = "获取头像流程失败：缺少演员ID (personId)。";
      showMessage('error', errorMsg);
      return { status: 'error', message: errorMsg };
    }

    isFetchingTmdbActor.value = true;
    tmdbActorCandidates.value = [];
    tmdbSingleActorCandidate.value = null;
    tmdbActorImages.value = [];
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/actors/${personId}/avatar-flow`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(avatarFlowState.value),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取头像流程失败');
      if (data.warnings?.length > 0) data.warnings.forEach(warn => showMessage('warning', warn));
      
      const details = data.intervention_details || {};
      if (details.next_request_patch) {
        updateAvatarFlowState(details.next_request_patch);
      }

      // --- 核心修改：简化ID更新逻辑 ---
      if (details.context && details.context.person && details.context.person.id) {
        console.log(`➡️ [调试-Store] 步骤2.1: 从后端响应中提取到 TMDB Person ID: ${details.context.person.id}`);
        updateAvatarFlowState({ confirmed_tmdb_person_id: details.context.person.id });
      }
      // --- 修改结束 ---

      if (data.status === 'success') {
        tmdbActorImages.value = data.images;
      } else if (data.status.startsWith('tmdb_')) {
        if (details.status === 'single_actor_confirm') tmdbSingleActorCandidate.value = details.context;
        else if (details.status === 'context_manual_selection' || details.status === 'manual_actor_selection') tmdbActorCandidates.value = details.candidates;
      }
      
      return data;
    } catch (error) {
      showMessage('error', `获取头像时出错: ${error.message}`);
      return { status: 'error', message: error.message };
    } finally {
      isFetchingTmdbActor.value = false;
    }
  }


  const fetchLibraryItems = async (libraryId, isSilentRefresh = false) => {
    if (!libraryId) return
    if (!isSilentRefresh) isLoadingItems.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/items/${libraryId}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '获取媒体项失败')
      mediaItems.value = data
    } catch (error) {
      showMessage('error', `获取媒体项列表失败: ${error.message}`)
    } finally {
      isLoadingItems.value = false
    }
  }

  const searchAllMedia = async (query) => {
    if (!query) { showMessage('warning', '请输入搜索关键词'); return; }
    isSearchingGlobally.value = true;
    globalSearchResults.value = [];
    try {
      const response = await fetch(`${API_BASE_URL}/api/media/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '全局搜索失败');
      if (data.length === 0) showMessage('info', '全局搜索未找到相关媒体。');
      globalSearchResults.value = data;
    } catch (error) {
      showMessage('error', `全局搜索失败: ${error.message}`);
    } finally {
      isSearchingGlobally.value = false;
    }
  };

  const clearGlobalSearch = () => { globalSearchResults.value = []; };

  const fetchItemActors = async (itemId) => {
    if (!itemId) return
    isLoadingActors.value = true
    actors.value = []
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/actors/${itemId}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '获取演员列表失败')
      actors.value = data.map(actor => ({ ...actor, isVisible: false, avatarUrl: '' }))
    } catch (error) {
      showMessage('error', `获取演员列表失败: ${error.message}`)
    } finally {
      isLoadingActors.value = false
    }
  }

  // frontend/src/stores/actorGallery.js (函数替换)

  const uploadAvatar = async (personId, image, newName = null) => {
    isUploading.value = true;
    try {
      let imageUrl = '';
      if (image.source === 'douban') {
        imageUrl = image.file_path;
      } else {
        imageUrl = `${TMDB_IMAGE_BASE_URL}${TMDB_IMAGE_SIZES.original}${image.file_path}`;
      }

      const payload = {
        person_id: personId,
        image_url: imageUrl,
        new_name: newName,
        source: image.source,
        tmdb_person_id: avatarFlowState.value.confirmed_tmdb_person_id || null,
      };
      
      // --- 新增 ---
      console.log('➡️ [调试-Store] 步骤3: 构建上传Payload。最终发送给后端的数据:', payload);
      // --- 新增结束 ---

      const response = await fetch(`${API_BASE_URL}/api/gallery/actors/upload-from-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '上传失败');
      showMessage('success', data.message || '操作成功！请稍后手动刷新查看。');
      return true;
    } catch (error) {
      showMessage('error', `头像上传失败: ${error.message}`);
      return false;
    } finally {
      isUploading.value = false;
    }
  };
  
  const uploadAvatarFromLocal = async (personId, file, newName = null) => {
    isUploading.value = true
    const formData = new FormData()
    formData.append('file', file)
    if (newName) formData.append('new_name', newName)
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/actors/${personId}/upload-local`, {
        method: 'POST',
        body: formData,
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '上传失败')
      showMessage('success', data.message || '操作成功！请稍后手动刷新查看。')
      return true
    } catch (error) {
      showMessage('error', `本地头像上传失败: ${error.message}`)
      return false
    } finally {
      isUploading.value = false
    }
  }
  
  async function _uploadImageFromUrl(endpoint, payload, successMessage) {
    isUploading.value = true;
    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '上传失败');
      showMessage('success', successMessage);
      return true;
    } catch (error) {
      showMessage('error', `图片上传失败: ${error.message}`);
      return false;
    } finally {
      isUploading.value = false;
    }
  }

  const uploadPosterFromUrl = (itemId, imageUrl, source) => _uploadImageFromUrl('/api/gallery/items/upload-poster-from-url', { item_id: itemId, image_url: imageUrl, source: source }, '海报上传成功！');
  const uploadBackdropFromUrl = (itemId, imageUrl) => _uploadImageFromUrl('/api/gallery/items/upload-backdrop-from-url', { item_id: itemId, image_url: imageUrl }, '背景图上传成功！');
  const uploadLogoFromUrl = (itemId, imageUrl) => _uploadImageFromUrl('/api/gallery/items/upload-logo-from-url', { item_id: itemId, image_url: imageUrl }, 'Logo上传成功！');

  async function fetchTmdbIdFlow(payload) {
    isFetchingTmdb.value = true;
    tmdbCandidates.value = [];
    tmdbSingleCandidate.value = null;
    tmdbImages.value = [];
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/tmdb-images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取TMDB ID流程失败');
      if (data.status === 'success') tmdbImages.value = data.images;
      else if (data.status === 'manual_selection') tmdbCandidates.value = data.candidates;
      else if (data.status === 'single_candidate_confirm') tmdbSingleCandidate.value = data.candidates[0];
      else showMessage('info', data.message || '未找到匹配项。');
      return data.status;
    } catch (error) {
      showMessage('error', `处理TMDB匹配时出错: ${error.message}`);
      return 'error';
    } finally {
      isFetchingTmdb.value = false;
    }
  }

  async function confirmTmdbIdAndFetchImages(payload) {
    isFetchingTmdb.value = true;
    tmdbImages.value = [];
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/confirm-and-fetch-images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '确认ID并获取图片失败');
      if (data.status !== 'success') showMessage('error', data.message || '获取图片列表失败。');
      tmdbImages.value = data.images; // 即使失败也尝试更新
      return 'success';
    } catch (error) {
      showMessage('error', `获取图片列表时出错: ${error.message}`);
      return 'error';
    } finally {
      isFetchingTmdb.value = false;
    }
  }

  async function fetchCombinedPosters(itemId) {
    isFetchingTmdb.value = true;
    tmdbImages.value = [];
    try {
      const response = await fetch(`${API_BASE_URL}/api/gallery/combined-posters/${itemId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '获取海报列表失败');
      if (data.warnings?.length > 0) data.warnings.forEach(warn => showMessage('warning', warn));
      if (data.success) {
        tmdbImages.value = data.images;
        return 'success';
      } else {
        showMessage('error', '获取海报列表失败。');
        return 'error';
      }
    } catch (error) {
      showMessage('error', `获取海报时出错: ${error.message}`);
      return 'error';
    } finally {
      isFetchingTmdb.value = false;
    }
  }

  return {
    isLoadingItems, isLoadingActors, isUploading,
    mediaItems, actors,
    isSearchingGlobally, globalSearchResults,
    isFetchingTmdb, tmdbCandidates, tmdbImages, tmdbSingleCandidate,
    isFetchingTmdbActor, tmdbActorCandidates, tmdbSingleActorCandidate, tmdbActorImages,
    avatarFlowState,
    fetchLibraryItems, fetchItemActors,
    searchAllMedia, clearGlobalSearch,
    uploadAvatar, uploadAvatarFromLocal,
    uploadPosterFromUrl, uploadBackdropFromUrl, uploadLogoFromUrl,
    fetchTmdbIdFlow, confirmTmdbIdAndFetchImages, fetchCombinedPosters,
    startAndFetchAvatarFlow, updateAvatarFlowState, fetchAvatarFlow,
  }
})