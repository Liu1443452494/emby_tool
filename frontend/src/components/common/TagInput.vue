<!-- frontend/src/components/common/TagInput.vue (新增文件) -->
<template>
  <div class="tag-input-container">
    <el-tag
      v-for="tag in modelValue"
      :key="tag"
      closable
      :disable-transitions="false"
      @close="handleClose(tag)"
      class="tag-item"
    >
      {{ tag }}
    </el-tag>
    <el-input
      v-model="inputValue"
      class="input-new-tag"
      size="small"
      :placeholder="placeholder"
      @keyup.enter="handleInputConfirm"
      @blur="handleInputConfirm"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue';

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => []
  },
  placeholder: {
    type: String,
    default: '添加标签...'
  }
});

const emit = defineEmits(['update:modelValue']);

const inputValue = ref('');

const handleClose = (tag) => {
  const newTags = props.modelValue.filter(t => t !== tag);
  emit('update:modelValue', newTags);
};

const handleInputConfirm = () => {
  if (inputValue.value && !props.modelValue.includes(inputValue.value)) {
    emit('update:modelValue', [...props.modelValue, inputValue.value]);
  }
  inputValue.value = '';
};
</script>

<style scoped>
.tag-input-container {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
}
.tag-item {
  margin-right: 5px;
}
.input-new-tag {
  width: 150px;
}
</style>