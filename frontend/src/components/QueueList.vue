<script setup>
import { computed } from 'vue'
import JobCard from './JobCard.vue'
import { useWebSocket } from '../composables/useWebSocket.js'

const { jobs } = useWebSocket()

const sorted = computed(() =>
  [...jobs.values()].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
)
const activeCount = computed(
  () =>
    sorted.value.filter((j) =>
      ['queued', 'downloading', 'processing'].includes(j.status)
    ).length
)
</script>

<template>
  <section>
    <div class="flex items-baseline justify-between px-1 mb-3">
      <h2 class="text-title3 font-semibold tracking-tight">佇列</h2>
      <span v-if="activeCount" class="text-footnote text-label-2">
        {{ activeCount }} 個進行中
      </span>
    </div>

    <div
      v-if="!sorted.length"
      class="card px-6 py-14 text-center"
    >
      <p class="text-subhead text-label-2">目前沒有任務</p>
      <p class="text-footnote text-label-3 mt-1">送出的下載會出現在這裡，並即時更新進度。</p>
    </div>

    <TransitionGroup v-else tag="div" name="list" class="space-y-3">
      <JobCard v-for="job in sorted" :key="job.id" :job="job" />
    </TransitionGroup>
  </section>
</template>

<style scoped>
.list-enter-active,
.list-leave-active {
  transition: opacity 0.3s var(--ease-sheet), transform 0.3s var(--ease-sheet);
}
.list-enter-from,
.list-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}
/* Cards below a removed one glide up instead of snapping. */
.list-move {
  transition: transform 0.3s var(--ease-sheet);
}
</style>
