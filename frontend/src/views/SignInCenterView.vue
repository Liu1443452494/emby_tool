<!-- frontend/src/views/SignInCenterView.vue (完整文件覆盖) -->
<template>
  <div class="signin-center-page">
    <div class="page-header">
      <h2>插件中心</h2>
      <p>集中管理所有插件。</p>
    </div>

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

  </div>
</template>

<script setup>
import { onMounted } from 'vue';
import { useSignInCenterStore } from '@/stores/signInCenter';
import SignInCard from '@/components/SignInCard.vue';

const store = useSignInCenterStore();

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

.tasks-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
  overflow-y: auto;
  padding: 20px 0;
  flex-grow: 1;
}
</style>