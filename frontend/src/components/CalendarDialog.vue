<!-- frontend/src/components/CalendarDialog.vue (新文件) -->
<template>
  <el-dialog
    v-model="dialogVisible"
    :title="`${calendarTitle} - 播出日历`"
    width="80%"
    top="5vh"
    destroy-on-close
    @close="$emit('update:visible', false)"
  >
    <div class="calendar-container">
      <el-calendar v-model="calendarDate" :first-day-of-week="1">
        <template #header="{ date }">
          <span>{{ date }}</span>
          <el-button-group>
            <el-button @click="selectDate('prev-month')">上个月</el-button>
            <el-button @click="selectDate('today')">今天</el-button>
            <el-button @click="selectDate('next-month')">下个月</el-button>
          </el-button-group>
        </template>
        <template #date-cell="{ data }">
          <div class="date-cell" :class="{ 'is-today': data.isToday }">
            <div class="day-number">{{ data.day.split('-').slice(2).join('-') }}</div>
            <div v-if="calendarData[data.day]" class="events-container">
              <div 
                v-for="(event, index) in calendarData[data.day]" 
                :key="index" 
                class="event-item"
              >
                <el-image :src="event.poster" fit="cover" class="event-poster" lazy />
                <div class="event-info">
                  <span class="event-name">{{ event.name }}</span>
                  <span class="event-episode">{{ event.episodesText }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </el-calendar>
    </div>
  </el-dialog>
</template>

<!-- frontend/src/components/CalendarDialog.vue (script setup 替换) -->
<script setup>
import { ref, watch, computed } from 'vue';
import { useMediaStore } from '@/stores/media';
import { useChasingCenterStore } from '@/stores/chasingCenter';
import _ from 'lodash';

const props = defineProps({
  visible: {
    type: Boolean,
    required: true,
  },
  seriesData: {
    type: Object,
    default: () => null,
  },
});

const emit = defineEmits(['update:visible']);

const mediaStore = useMediaStore();
const chasingStore = useChasingCenterStore();
const serverUrl = computed(() => mediaStore.appConfig?.server_config?.server);
const apiKey = computed(() => mediaStore.appConfig?.server_config?.api_key);

const dialogVisible = ref(false);
const calendarDate = ref(new Date());
const calendarData = ref({});
const calendarTitle = ref('');

// 监听父组件传入的可见性
watch(() => props.visible, (newVal) => {
  dialogVisible.value = newVal;
  if (newVal && props.seriesData) {
    // 当对话框可见时，处理从 store 获取的数据
    processCalendarData();
  }
});

// 监听 store 中日历数据的变化
watch(() => chasingStore.calendarData, (newData) => {
  if (props.visible && props.seriesData) {
    processCalendarData();
  }
});

const processCalendarData = () => {
  const series = props.seriesData;
  if (!series) return;

  calendarTitle.value = series.name;
  const posterUrl = `${serverUrl.value}/Items/${series.emby_id}/Images/Primary?api_key=${apiKey.value}&fillWidth=100&quality=90`;
  
  const groupedByDate = chasingStore.calendarData;
  const processedData = {};
  let firstEventDate = null;

  for (const date in groupedByDate) {
    const episodesOnDate = groupedByDate[date];
    const episodesText = episodesOnDate.map(ep => `第${ep.episode_number}集`).join(', ');
    
    processedData[date] = [{
      name: series.name,
      poster: posterUrl,
      episodesText: episodesText,
    }];

    if (!firstEventDate) {
      firstEventDate = new Date(date);
    }
  }
  
  calendarData.value = processedData;
  if (firstEventDate) {
    calendarDate.value = firstEventDate;
  } else {
    calendarDate.value = new Date();
  }
};

const selectDate = (val) => {
  if (val === 'today') {
    calendarDate.value = new Date();
    return;
  }
  const date = calendarDate.value;
  const month = val === 'prev-month' ? date.getMonth() - 1 : date.getMonth() + 1;
  calendarDate.value = new Date(date.setMonth(month));
};
</script>

<style scoped>
.calendar-container {
  height: 75vh;
}
.calendar-container :deep(.el-calendar__body) {
  padding: 12px 20px;
  height: calc(100% - 60px); /* 减去 header 的高度 */
}
.calendar-container :deep(.el-calendar-table) {
  height: 100%;
}
.calendar-container :deep(.el-calendar-table .el-calendar-day) {
  height: auto;
  padding: 4px;
}
.date-cell {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.day-number {
  font-size: 14px;
  text-align: left;
  padding: 4px;
  color: var(--el-text-color-primary);
}
.events-container {
  flex-grow: 1;
  overflow-y: auto;
  padding: 0 4px 4px 4px;
}
.event-item {
  display: flex;
  align-items: center;
  background-color: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 5px;
  margin-top: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.event-item:hover {
  transform: scale(1.05);
  box-shadow: var(--el-box-shadow-light);
}
.event-poster {
  width: 30px;
  height: 45px;
  border-radius: 4px;
  flex-shrink: 0;
  margin-right: 8px;
}
.event-info {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.event-name {
  font-weight: bold;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--el-text-color-primary);
}
.event-episode {
  color: var(--el-text-color-secondary);
}.date-cell.is-today .day-number {
  background-color: var(--el-color-primary);
  color: #fff;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  padding: 0;
}
</style>