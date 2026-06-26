<script setup>
import { computed } from 'vue'

const props = defineProps({ job: { type: Object, required: true } })

const STATUS_META = {
  queued: { label: '排隊中', class: 'bg-gray-500/15 text-gray-400' },
  downloading: { label: '下載中', class: 'bg-sky-500/15 text-sky-400' },
  processing: { label: '合併中', class: 'bg-amber-500/15 text-amber-400' },
  needs_selection: { label: '請選擇', class: 'bg-violet-500/15 text-violet-400' },
  ready: { label: '可下載', class: 'bg-emerald-500/15 text-emerald-400' },
  done: { label: '已取走', class: 'bg-gray-500/15 text-gray-500' },
  failed: { label: '失敗', class: 'bg-rose-500/15 text-rose-400' },
  cancelled: { label: '已取消', class: 'bg-gray-500/15 text-gray-500' },
  expired: { label: '已過期', class: 'bg-gray-500/15 text-gray-500' },
}

const meta = computed(() => STATUS_META[props.job.status] ?? STATUS_META.queued)
const isActive = computed(() => ['downloading', 'processing'].includes(props.job.status))

// Map the raw backend error (a technical, possibly multi-line string) to a
// plain-language explanation. First matching pattern wins; the raw text stays
// available in a collapsible <details> for debugging.
const ERROR_HINTS = [
  [/no space left|disk quota|errno 28/i, '伺服器暫存空間不足 —— 這支影片太大（合併時約需兩倍空間）。請聯絡管理員擴充空間，或改抓較短／較低畫質的版本。'],
  [/sign ?in|log ?in|login|private|members?-only|age[- ]?restrict|account/i, '此影片需要登入才能觀看。請展開「進階選項」貼上你的帳號 cookie 後重試。'],
  [/\b403\b|forbidden|access denied/i, '來源拒絕存取（403）—— 可能是防盜連、地區限制，或需要登入 cookie。'],
  [/\b404\b|not found|unable to download webpage|410 gone/i, '找不到影片 —— 連結可能已失效或被移除。'],
  [/no media stream|found no media|unsupported url|no video formats/i, '無法從這個網頁辨識出影片來源。這類站的播放器有時不會一次就載入 —— 多數情況「再送一次」就會成功；若連續失敗才可能是真的不支援。'],
  [/conversion failed|postprocessing/i, '影片下載完成，但合併成 mp4 時失敗 —— 通常是暫存空間不足，詳見下方技術細節。'],
  [/timed out|timeout|connection reset|network|getaddrinfo|ssl/i, '連線逾時或網路錯誤 —— 來源伺服器沒有回應，稍後再試。'],
  [/ffmpeg exited|exited with code/i, '影片處理工具（ffmpeg）失敗 —— 來源串流可能已失效或格式異常，詳見下方技術細節。'],
]

const errorInfo = computed(() => {
  const raw = props.job.error
  if (!raw) return null
  const hint = ERROR_HINTS.find(([re]) => re.test(raw))
  const summary = hint ? hint[1] : '下載失敗 —— 詳見下方技術細節。'
  // Only show the raw block separately when it adds info beyond the summary.
  return { summary, detail: raw.trim() }
})

function formatBytes(b) {
  if (!b) return null
  const units = ['B', 'KB', 'MB', 'GB']
  let v = b, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

const sizeText = computed(() => formatBytes(props.job.filesize))

const downloadedText = computed(() => {
  const dl = formatBytes(props.job.downloaded)
  if (!dl) return null
  const total = formatBytes(props.job.filesize)
  return total ? `${dl} / ${total}` : dl
})

function candidateLabel(c, i) {
  const name = (() => { try { return new URL(c.url).pathname.split('/').pop() || c.url } catch { return c.url } })()
  const size = formatBytes(c.size)
  return `${i + 1}. ${c.kind.toUpperCase()} · ${name}${size ? ` · ${size}` : ''}`
}

async function select(index) {
  await fetch(`/api/jobs/${props.job.id}/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ index }),
  })
}

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
      <div class="flex justify-between text-xs mt-1.5">
        <span class="text-gray-400">
          {{ (job.progress ?? 0).toFixed(1) }}%
          <span v-if="downloadedText" class="text-gray-500"> · {{ downloadedText }}</span>
        </span>
        <span v-if="job.speed">
          <span class="text-emerald-400">{{ job.speed }}</span>
          <span class="text-sky-400"> · 剩餘 {{ job.eta || '–' }}</span>
        </span>
      </div>
    </div>

    <div v-if="job.status === 'needs_selection' && job.candidates" class="mt-3">
      <p class="text-xs text-violet-300">
        這個網頁有多個影片來源，無法自動判斷哪個是正片。請選擇正確的那個：
      </p>
      <div class="flex flex-col gap-1.5 mt-2">
        <button
          v-for="(c, i) in job.candidates"
          :key="c.url"
          @click="select(i)"
          class="text-left text-xs bg-surface hover:bg-violet-500/15 border border-edge
                 hover:border-violet-500/40 rounded-lg px-3 py-2 transition-colors truncate"
          :title="c.url"
        >
          {{ candidateLabel(c, i) }}
        </button>
      </div>
    </div>

    <div v-if="errorInfo" class="mt-3">
      <p class="text-xs text-rose-400">{{ errorInfo.summary }}</p>
      <details class="mt-1 group">
        <summary class="text-[11px] text-gray-500 hover:text-gray-400 cursor-pointer select-none">
          技術細節
        </summary>
        <pre class="text-[11px] text-gray-500 mt-1 whitespace-pre-wrap break-all
                    bg-surface rounded-md p-2 max-h-40 overflow-auto">{{ errorInfo.detail }}</pre>
      </details>
    </div>

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
