<!-- frontend/src/views/SignInCenterView.vue (完整文件覆盖) -->
<template>
  <div class="signin-center-page">
    <div class="page-header">
      <h2>签到中心</h2>
      <p>集中管理所有站点的自动签到任务，保持您的账号活跃。</p>
    </div>

    <!-- --- 新增：通知设置入口 --- -->
    <div class="toolbar">
      <el-button @click="isTelegramDialogVisible = true" :icon="Bell">
        通知设置
      </el-button>
    </div>
    <!-- --- 新增结束 --- -->

    <div v-if="store.isLoading" class="loading-container">
      <el-skeleton :rows="5" animated />
    </div>

    <div v-else-if="store.modules.length > 0" class="tasks-container">
      <SignInCard 
        v-for="module in store.modules" 
        :key="module.id" 
        :module-data="module"
      />
    </div>
    
    <el-empty v-else description="后端未加载任何签到模块" />

    <!-- --- 新增：Telegram 设置对话框 --- -->
    <TelegramSettingsDialog
      v-if="isTelegramDialogVisible"
      v-model:visible="isTelegramDialogVisible"
    />
    <!-- --- 新增结束 --- -->
  </div>
</template>

<script setup>
import { ref, onMounted, defineAsyncComponent } from 'vue';
import { useSignInCenterStore } from '@/stores/signInCenter';
import SignInCard from '@/components/SignInCard.vue';
import { Bell } from '@element-plus/icons-vue';

// --- 新增：异步加载对话框组件 ---
const TelegramSettingsDialog = defineAsyncComponent(() => 
  import('@/components/TelegramSettingsDialog.vue')
);
// --- 新增结束 ---

const store = useSignInCenterStore();
const isTelegramDialogVisible = ref(false);

onMounted(() => {
  store.fetchModules();
});
</script>

<style scoped>
.signin-center-page {
  padding: 0 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page-header {
  padding: 20px 0;
  border-bottom: 1px solid var(--el-border-color-light);
  flex-shrink: 0;
}
.page-header h2 { margin: 0 0 8px 0; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); }

/* --- 新增：工具栏样式 --- */
.toolbar {
  padding: 15px 0;
  flex-shrink: 0;
}
/* --- 新增结束 --- */

.tasks-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
  overflow-y: auto;
  padding-bottom: 20px;
  flex-grow: 1;
}
</style>