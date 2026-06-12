<script setup>
import { computed } from 'vue'
import JobCard from './JobCard.vue'
import { useWebSocket } from '../composables/useWebSocket.js'

const { jobs } = useWebSocket()

const sorted = computed(() =>
  [...jobs.values()].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
)
const activeCount = computed(
  () => sorted.value.filter((j) => ['queued', 'downloading', 'processing'].includes(j.status)).length
)
</script>

<template>
  <section>
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-medium text-gray-400">佇列</h2>
      <span v-if="activeCount" class="text-xs text-accent-soft">{{ activeCount }} 個任務進行中</span>
    </div>

    <p v-if="!sorted.length" class="text-center text-gray-600 text-sm py-12 border border-dashed border-edge rounded-2xl">
      目前沒有任務
    </p>

    <TransitionGroup v-else tag="div" name="list" class="space-y-3">
      <JobCard v-for="job in sorted" :key="job.id" :job="job" />
    </TransitionGroup>
  </section>
</template>

<style scoped>
.list-enter-active,
.list-leave-active {
  transition: all 0.25s ease;
}
.list-enter-from,
.list-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
