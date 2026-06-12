<script setup>
import { computed } from 'vue'

const props = defineProps({ job: { type: Object, required: true } })

const STATUS_META = {
  queued: { label: '排隊中', class: 'bg-gray-500/15 text-gray-400' },
  downloading: { label: '下載中', class: 'bg-sky-500/15 text-sky-400' },
  processing: { label: '合併中', class: 'bg-amber-500/15 text-amber-400' },
  ready: { label: '可下載', class: 'bg-emerald-500/15 text-emerald-400' },
  done: { label: '已取走', class: 'bg-gray-500/15 text-gray-500' },
  failed: { label: '失敗', class: 'bg-rose-500/15 text-rose-400' },
  cancelled: { label: '已取消', class: 'bg-gray-500/15 text-gray-500' },
  expired: { label: '已過期', class: 'bg-gray-500/15 text-gray-500' },
}

const meta = computed(() => STATUS_META[props.job.status] ?? STATUS_META.queued)
const isActive = computed(() => ['downloading', 'processing'].includes(props.job.status))

const sizeText = computed(() => {
  const b = props.job.filesize
  if (!b) return null
  const units = ['B', 'KB', 'MB', 'GB']
  let v = b, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
})

async function remove() {
  await fetch(`/api/jobs/${props.job.id}`, { method: 'DELETE' })
}
</script>

<template>
  <div class="bg-panel border border-edge rounded-2xl p-5">
    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <p class="font-medium text-sm truncate" :title="job.title || job.url">
          {{ job.title || job.url }}
        </p>
        <p class="text-xs text-gray-500 truncate mt-0.5">
          {{ job.url }}
          <span class="ml-2 text-gray-600">via {{ job.handler }}</span>
        </p>
      </div>
      <span class="text-xs px-2.5 py-1 rounded-full whitespace-nowrap" :class="meta.class">
        {{ meta.label }}
      </span>
    </div>

    <div v-if="isActive" class="mt-4">
      <div class="h-1.5 bg-surface rounded-full overflow-hidden">
        <div
          class="h-full bg-accent rounded-full transition-all duration-300"
          :class="{ 'animate-pulse': job.status === 'processing' }"
          :style="{ width: `${job.progress || 2}%` }"
        ></div>
      </div>
      <div class="flex justify-between text-xs text-gray-500 mt-1.5">
        <span>{{ (job.progress ?? 0).toFixed(1) }}%</span>
        <span v-if="job.speed">{{ job.speed }} · 剩餘 {{ job.eta || '–' }}</span>
      </div>
    </div>

    <p v-if="job.error" class="text-xs text-rose-400/80 mt-3 break-all">{{ job.error }}</p>

    <div class="flex items-center gap-3 mt-4">
      <a
        v-if="job.status === 'ready'"
        :href="`/api/jobs/${job.id}/download`"
        class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium
               px-4 py-2 rounded-lg transition-colors"
      >
        ⬇ 下載{{ sizeText ? ` (${sizeText})` : '' }}
      </a>
      <button
        @click="remove"
        class="text-xs text-gray-500 hover:text-rose-400 px-2 py-2 transition-colors"
      >
        {{ ['queued', 'downloading', 'processing'].includes(job.status) ? '取消' : '移除' }}
      </button>
    </div>
  </div>
</template>
