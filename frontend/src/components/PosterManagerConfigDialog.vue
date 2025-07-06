<template>
  <el-dialog :model-value="visible" @update:model-value="$emit('update:visible', $event)" title="配置中心 - 海报管理器"
    width="80%" top="5vh" destroy-on-close @open="handleOpen">
    <div class="config-dialog-content">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="仓库管理" name="repos">
          <div class="repo-management">
            <div class="repo-toolbar">
              <el-button @click="store.fetchStats(true)" :loading="store.isStatsLoading">刷新仓库状态</el-button>
            </div>
            <el-table :data="localConfig.github_repos" style="width: 100%" height="100%" border row-key="repo_url">
              <el-table-column label="优先级" type="index" width="80" align="center" />
              <el-table-column label="仓库名称" min-width="200">
                <template #default="scope">{{ getRepoName(scope.row.repo_url) }}</template>
              </el-table-column>
              <el-table-column label="状态" min-width="300">
                <template #default="scope">
                  <div class="repo-status-cell">
                    <el-progress :percentage="getRepoUsagePercent(scope.row)" :color="getRepoUsageColor(scope.row)"
                      :stroke-width="15" :show-text="false" class="status-progress" />
                    <span class="progress-text">{{ getRepoUsageText(scope.row) }}</span>
                    <span class="update-time-text">{{ getRelativeTime(scope.row.state.last_checked) }}</span>
                    <el-tag v-if="getRepoUsagePercent(scope.row) > 95" type="danger" size="small" effect="light"
                      class="warning-tag">警告</el-tag>
                  </div>
                </template>
              </el-table-column>
              <!-- 核心修正 1: 调整操作列宽度，并将按钮改为 size="small" 的实心按钮 -->
              <el-table-column label="操作" width="220" align="center">
                <template #default="scope">
                  <div class="action-buttons-cell">
                    <el-button size="small" @click="moveRepo(scope.$index, -1)"
                      :disabled="scope.$index === 0">上移</el-button>
                    <el-button size="small" @click="moveRepo(scope.$index, 1)"
                      :disabled="scope.$index === localConfig.github_repos.length - 1">下移</el-button>
                    <el-button type="primary" size="small" @click="editRepo(scope.row, scope.$index)">编辑</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <el-button @click="addRepo" :icon="Plus" style="margin-top: 15px;">添加新仓库</el-button>
          </div>
        </el-tab-pane>
        <el-tab-pane label="全局参数" name="params">
          <el-form :model="localConfig" label-position="top" class="global-params-form">
            <el-form-item label="全局个人访问令牌 (PAT)">
              <el-input v-model="localConfig.global_personal_access_token" type="password" show-password
                placeholder="用于所有未单独配置PAT的仓库" />
            </el-form-item>
            <el-form-item label="仓库容量阈值 (MB)">
              <el-input-number v-model="localConfig.repository_size_threshold_mb" :min="100" :max="1000" />
              <div class="form-item-description">建议值 900MB。系统将根据此阈值在本地预先规划文件分发，以避免上传时超容失败。不建议设置超过
                1000MB，因为GitHub仓库的硬性限制为1GB。
              </div>
            </el-form-item>
            <el-form-item label="API 冷却时间 (秒)">
              <div class="cooldown-group">
                <div class="cooldown-item">
                  <span>图片下载冷却:</span>
                  <el-input-number v-model="localConfig.image_download_cooldown_seconds" :min="0" :step="0.1"
                    :precision="1" />
                </div>
                <div class="cooldown-item">
                  <span>文件上传冷却:</span>
                  <el-input-number v-model="localConfig.file_upload_cooldown_seconds" :min="0" :step="0.1"
                    :precision="1" />
                </div>
              </div>
            </el-form-item>
            <el-form-item label="覆盖开关">
              <el-switch v-model="localConfig.overwrite_remote_files" active-text="备份时，覆盖远程图床已存在的同名文件" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="本地缓存" name="cache">
          <el-form :model="localConfig" label-position="top" class="global-params-form">
            <el-form-item label="本地缓存路径">
              <el-input v-model="localConfig.local_cache_path" placeholder="例如: /app/data/poster_cache" />
              <div class="form-item-description">
                <p>所有从 Emby 下载或待上传的图片都将存储在此目录。</p>
                <p>路径结构约定: <code>{{ localConfig.local_cache_path || '{本地缓存路径}' }}/{TMDB_ID}/{图片类型}.{后缀}</code></p>
                <p>文件命名约定: 系统将严格扫描和处理 <code>poster.jpg</code>, <code>clearlogo.png</code>, <code>fanart.jpg</code> 文件。
                </p>
              </div>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="primary" @click="handleSave" :loading="store.isSaving">保存所有配置</el-button>
    </template>

    <!-- 编辑仓库对话框 -->
    <el-dialog v-model="isEditRepoDialogVisible" title="编辑仓库" width="600px" append-to-body>
      <el-form :model="editingRepo" label-position="top">
        <el-form-item label="仓库 URL (必填)">
          <el-input v-model="editingRepo.repo_url" />
        </el-form-item>
        <el-form-item label="分支 (默认main)">
          <el-input v-model="editingRepo.branch" />
        </el-form-item>
        <el-form-item label="仓库级 PAT (可选)">
          <el-input v-model="editingRepo.personal_access_token" type="password" show-password
            placeholder="留空则使用全局PAT" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="danger" @click="deleteRepo" style="float: left;">删除此仓库</el-button>
        <el-button @click="isEditRepoDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveRepo">保存</el-button>
      </template>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { ref, computed } from 'vue';
import _ from 'lodash';
import { usePosterManagerStore } from '@/stores/posterManager';
import { ElMessage, ElMessageBox } from 'element-plus';
import { ArrowUp, ArrowDown, Edit, Plus } from '@element-plus/icons-vue';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';
dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

defineProps({ visible: Boolean });
const emit = defineEmits(['update:visible']);

const store = usePosterManagerStore();
const activeTab = ref('repos');
const localConfig = ref({});

const isEditRepoDialogVisible = ref(false);
const editingRepo = ref(null);
const editingRepoIndex = ref(-1);

const handleOpen = () => {
  localConfig.value = _.cloneDeep(store.config);
};

const getRepoName = (url) => {
  if (!url) return '未命名仓库';
  const match = url.match(/github\.com\/([^/]+\/[^/]+)/);
  return match ? match[1] : url;
};

const getRepoUsagePercent = (repo) => {
  const used = repo.state.size_bytes || 0;
  const total = localConfig.value.repository_size_threshold_mb * 1024 * 1024;
  if (!total) return 0;
  return Math.round((used / total) * 100);
};

const getRepoUsageColor = (repo) => {
  const p = getRepoUsagePercent(repo);
  if (p > 95) return '#F56C6C';
  if (p > 80) return '#E6A23C';
  return '#67C23A';
};

const getRepoUsageText = (repo) => {
  const used = repo.state.size_bytes || 0;
  const total = localConfig.value.repository_size_threshold_mb * 1024 * 1024;
  return `${store.formatBytes(used)} / ${store.formatBytes(total)}`;
};
const getRelativeTime = (isoString) => {
  if (!isoString) return '(从未更新)';
  return `(更新于: ${dayjs(isoString).fromNow()})`;
};

const moveRepo = (index, direction) => {
  const repos = localConfig.value.github_repos;
  const newIndex = index + direction;
  if (newIndex < 0 || newIndex >= repos.length) return;
  [repos[index], repos[newIndex]] = [repos[newIndex], repos[index]];
};

const addRepo = () => {
  editingRepo.value = { repo_url: '', branch: 'main', personal_access_token: '', state: { size_kb: 0, last_checked: '' } };
  editingRepoIndex.value = -1;
  isEditRepoDialogVisible.value = true;
};

const editRepo = (repo, index) => {
  editingRepo.value = _.cloneDeep(repo);
  editingRepoIndex.value = index;
  isEditRepoDialogVisible.value = true;
};

const saveRepo = () => {
  if (!editingRepo.value.repo_url) {
    ElMessage.error('仓库 URL 不能为空');
    return;
  }
  if (editingRepoIndex.value > -1) {
    localConfig.value.github_repos[editingRepoIndex.value] = editingRepo.value;
  } else {
    localConfig.value.github_repos.push(editingRepo.value);
  }
  isEditRepoDialogVisible.value = false;
};

const deleteRepo = async () => {
  try {
    await ElMessageBox.confirm('确定要删除这个仓库吗？', '警告', { type: 'warning' });
    if (editingRepoIndex.value > -1) {
      localConfig.value.github_repos.splice(editingRepoIndex.value, 1);
    }
    isEditRepoDialogVisible.value = false;
  } catch (error) { /* a */ }
};

const handleSave = async () => {
  const success = await store.saveConfig(localConfig.value);
  if (success) {
    emit('update:visible', false);
  }
};
</script>

<style scoped>
.config-dialog-content { height: 70vh; display: flex; flex-direction: column; }
.repo-management { height: 100%; display: flex; flex-direction: column; }
.repo-toolbar { margin-bottom: 15px; }
.repo-management .el-table { flex-grow: 1; }


/* frontend/src/components/PosterManagerConfigDialog.vue (样式规则替换 - 固定宽度版) */

.repo-status-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  font-size: 12px;
}
.status-progress {
  /* --- 核心修改 1: 固定进度条的宽度 --- */
  width: 320px; /* 给进度条一个固定的宽度 */
  flex-shrink: 0; /* 防止它被压缩 */
}
.status-progress :deep(.el-progress__text) {
  display: none;
}
.progress-text { 
  color: var(--el-text-color-secondary); 
  font-family: monospace;
  white-space: nowrap;
  flex-shrink: 0;
}
.update-time-text { 
  color: var(--el-text-color-placeholder); 
  white-space: nowrap;
  flex-shrink: 0;
  /* --- 核心修改 2: 让更新时间占据所有剩余空间并靠右对齐 --- */
  margin-left: auto;
  text-align: right;
}
.warning-tag {
  flex-shrink: 0;
  margin-left: 10px; /* 与更新时间保持一点距离 */
}

/* --- 核心修正 3: 操作按钮单元格样式 --- */
.action-buttons-cell {
  display: flex;
  justify-content: center;
  gap: 10px;
}

.global-params-form { padding: 20px; max-width: 800px; }
.form-item-description { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-top: 4px; }
.cooldown-group { display: flex; gap: 30px; }
.cooldown-item { display: flex; align-items: center; gap: 10px; }

/* --- 核心修正 4: 对话框圆角 --- */
:deep(.el-dialog) {
  border-radius: 12px;
}
</style>