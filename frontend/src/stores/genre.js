// frontend/src/stores/genre.js (修改后)
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
// --- 核心修改 1: 导入 API 配置 ---
import { API_BASE_URL } from '@/config/apiConfig';

export const useGenreStore = defineStore('genre', () => {
    const serverGenres = ref([])
    const mapping = ref({}) 
    const standardMapping = ref({})
    
    const previewResults = ref([]) 
    const consoleOutput = ref('') 
    const isTableLoading = ref(false)
    const isPreviewLoading = ref(false)
    const activePreviewTaskId = ref(null)
    const activeApplyTaskId = ref(null)

    const tableData = computed(() => {
        return serverGenres.value.map(genre => ({
            id: genre.id,
            original: genre.name,
            replacement: mapping.value[genre.name] || ''
        }))
    })

    async function fetchServerGenres() {
        isTableLoading.value = true
        try {
            await fetchStandardMapping()
            // --- 核心修改 2: 使用导入的常量 ---
            const response = await fetch(`${API_BASE_URL}/api/genres`)
            if (!response.ok) throw new Error('获取服务器类型失败')
            
            const genresFromServer = await response.json()
            serverGenres.value = genresFromServer
            
            const newOperatingMapping = {}
            genresFromServer.forEach(g => {
                newOperatingMapping[g.name] = standardMapping.value[g.name] || ''
            })
            mapping.value = newOperatingMapping
            consoleOutput.value = '已从服务器加载类型，并应用了标准映射规则。'

        } catch (error) {
            ElMessage.error(error.message)
        } finally {
            isTableLoading.value = false
        }
    }

    async function fetchStandardMapping() {
        try {
            // --- 核心修改 3: 使用导入的常量 ---
            const response = await fetch(`${API_BASE_URL}/api/genres/standard-mapping`)
            if (!response.ok) throw new Error('获取标准映射规则失败')
            standardMapping.value = await response.json()
        } catch (error) {
            ElMessage.error(error.message)
        }
    }

    async function saveStandardMapping(newMapping) {
        try {
            // --- 核心修改 4: 使用导入的常量 ---
            const response = await fetch(`${API_BASE_URL}/api/genres/standard-mapping`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mapping: newMapping })
            })
            if (!response.ok) throw new Error('保存标准映射规则失败')
            standardMapping.value = newMapping
            ElMessage.success('标准映射规则已保存到配置文件')
        } catch (error) {
            ElMessage.error(error.message)
        }
    }

    async function startPreview(request) {
        isPreviewLoading.value = true
        previewResults.value = []
        consoleOutput.value = '正在启动预览任务...\n'
        try {
            // --- 核心修改 5: 使用导入的常量 ---
            const response = await fetch(`${API_BASE_URL}/api/genres/preview`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mapping: mapping.value, ...request })
            })
            const data = await response.json()
            if (!response.ok) throw new Error(data.detail || '启动预览任务失败')
            
            activePreviewTaskId.value = data.task_id
            ElMessage.success(data.message)

        } catch (error) {
            consoleOutput.value += `\n错误: ${error.message}\n`
            ElMessage.error(error.message)
            isPreviewLoading.value = false; // 启动失败时，重置加载状态
        }
    }

    async function startApply() {
        if (!previewResults.value || previewResults.value.length === 0) {
            ElMessage.warning('没有可应用的修改，请先运行预览。')
            return
        }
        isPreviewLoading.value = true
        try {
            // --- 核心修改 6: 使用导入的常量 ---
            const response = await fetch(`${API_BASE_URL}/api/genres/apply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items_to_apply: previewResults.value })
            })
            const data = await response.json()
            if (!response.ok) throw new Error('启动应用任务失败')
            activeApplyTaskId.value = data.task_id
            ElMessage.success(data.message)
        } catch (error) {
            ElMessage.error(error.message)
            isPreviewLoading.value = false; // 启动失败时，重置加载状态
        }
    }
    
    function clearActiveApplyTask() {
        activeApplyTaskId.value = null
    }
    function clearActivePreviewTask() {
        activePreviewTaskId.value = null
    }

    return {
        tableData, mapping, previewResults, consoleOutput, isTableLoading, isPreviewLoading,
        activePreviewTaskId, activeApplyTaskId, standardMapping,
        fetchServerGenres, fetchStandardMapping, saveStandardMapping,
        startPreview, startApply,
        clearActiveApplyTask, clearActivePreviewTask
    }
})