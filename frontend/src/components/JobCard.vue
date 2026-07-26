<script setup>
import { computed } from 'vue'
import { request } from '../composables/useApi.js'

const props = defineProps({ job: { type: Object, required: true } })

// Tinted status pills, one colour per meaning: blue = working, green = yours
// to take, red = broken, grey = nothing left to do.
const STATUS_META = {
  queued: { label: '排隊中', class: 'bg-fill text-label-2' },
  downloading: { label: '下載中', class: 'bg-accent-fill text-accent' },
  processing: { label: '合併中', class: 'bg-orange/15 text-orange' },
  needs_selection: { label: '請選擇', class: 'bg-purple/15 text-purple' },
  ready: { label: '可下載', class: 'bg-green/15 text-green' },
  done: { label: '已取走', class: 'bg-fill text-label-3' },
  failed: { label: '失敗', class: 'bg-red/15 text-red' },
  cancelled: { label: '已取消', class: 'bg-fill text-label-3' },
  expired: { label: '已過期', class: 'bg-fill text-label-3' },
}

const meta = computed(() => STATUS_META[props.job.status] ?? STATUS_META.queued)
// Before a handler reports a title there is only the URL, and printing it
// twice looks like a rendering bug.
const subtitle = computed(() => (props.job.title ? props.job.url : ''))
const isActive = computed(() => ['downloading', 'processing'].includes(props.job.status))
const isPending = computed(() =>
  ['queued', 'downloading', 'processing', 'needs_selection'].includes(props.job.status)
)

// Map the raw backend error (a technical, possibly multi-line string) to a
// plain-language explanation. First matching pattern wins; the raw text stays
// available in a collapsible <details> for debugging.
const ERROR_HINTS = [
  [/no space left|disk quota|errno 28/i, '伺服器暫存空間不足 —— 這支影片太大（合併時約需兩倍空間）。請聯絡管理員擴充空間，或改抓較短／較低畫質的版本。'],
  [/cannot see that channel|join it manually/i, '你的 Telegram 帳號看不到這個頻道。請先用正式的 Telegram App 加入該頻道，本工具不會替你加入。'],
  [/no Telegram session|log in again|session was revoked/i, '尚未登入 Telegram，或登入已失效。請到右上角「設定」重新登入。'],
  [/carries no downloadable file|is gone or not visible/i, '這則貼文沒有可下載的檔案，或已被刪除。'],
  [/flood wait/i, 'Telegram 暫時限流了這個帳號，請等訊息裡的時間過後再試。'],
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
  return {
    summary: hint ? hint[1] : '下載失敗 —— 詳見下方技術細節。',
    detail: raw.trim(),
  }
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
  const name = (() => {
    try {
      return new URL(c.url).pathname.split('/').pop() || c.url
    } catch {
      return c.url
    }
  })()
  const size = formatBytes(c.size)
  return `${i + 1}. ${c.kind.toUpperCase()} · ${name}${size ? ` · ${size}` : ''}`
}

async function select(index) {
  await request(`/api/jobs/${props.job.id}/select`, {
    method: 'POST',
    body: JSON.stringify({ index }),
  })
}

async function remove() {
  await request(`/api/jobs/${props.job.id}`, { method: 'DELETE' })
}
</script>

<template>
  <div class="card p-4 sm:p-5">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-subhead font-medium truncate" :title="job.title || job.url">
          {{ job.title || job.url }}
        </p>
        <p v-if="subtitle" class="text-footnote text-label-3 truncate mt-0.5" :title="job.url">
          {{ subtitle }}
        </p>
      </div>
      <span
        class="shrink-0 text-caption font-semibold px-2.5 py-1 rounded-full"
        :class="meta.class"
      >
        {{ meta.label }}
      </span>
    </div>

    <div v-if="isActive" class="mt-3.5">
      <div class="h-1.5 rounded-full bg-fill overflow-hidden">
        <div
          class="h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
          :class="{ 'animate-pulse': job.status === 'processing' }"
          :style="{ width: `${Math.max(job.progress || 0, 2)}%` }"
        ></div>
      </div>
      <div class="flex justify-between gap-3 text-footnote text-label-2 mt-1.5">
        <span class="truncate">
          {{ (job.progress ?? 0).toFixed(1) }}%
          <span v-if="downloadedText" class="text-label-3"> · {{ downloadedText }}</span>
        </span>
        <span v-if="job.speed" class="shrink-0 tabular-nums">
          {{ job.speed }}
          <span v-if="job.eta" class="text-label-3"> · 剩 {{ job.eta }}</span>
        </span>
      </div>
    </div>

    <div v-if="job.status === 'needs_selection' && job.candidates" class="mt-3.5">
      <p class="text-footnote text-label-2">
        這個網頁有多個影片來源，無法自動判斷哪個是正片，請選擇：
      </p>
      <div class="flex flex-col gap-1.5 mt-2">
        <button
          v-for="(c, i) in job.candidates"
          :key="c.url"
          class="text-left text-footnote bg-fill hover:bg-accent-fill rounded-[0.625rem]
                 px-3 py-2 truncate transition-colors"
          :title="c.url"
          @click="select(i)"
        >
          {{ candidateLabel(c, i) }}
        </button>
      </div>
    </div>

    <div v-if="errorInfo" class="mt-3.5">
      <p class="text-footnote text-red">{{ errorInfo.summary }}</p>
      <details class="mt-1.5">
        <summary class="text-caption text-label-3 cursor-pointer select-none">
          技術細節
        </summary>
        <pre class="text-caption text-label-2 mt-1.5 whitespace-pre-wrap break-all
                    bg-fill rounded-[0.625rem] p-2.5 max-h-40 overflow-auto">{{ errorInfo.detail }}</pre>
      </details>
    </div>

    <div class="flex items-center gap-2 mt-3">
      <a
        v-if="job.status === 'ready'"
        :href="`/api/jobs/${job.id}/download`"
        class="btn btn-filled !py-2 !px-4 text-footnote"
      >
        <svg viewBox="0 0 24 24" class="w-4 h-4" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 4v12m0 0 4.5-4.5M12 16l-4.5-4.5M4.5 19.5h15" />
        </svg>
        下載{{ sizeText ? `（${sizeText}）` : '' }}
      </a>
      <span
        v-else-if="sizeText && !isActive"
        class="text-footnote text-label-3"
      >
        {{ sizeText }}
      </span>
      <button class="btn btn-plain !text-label-2 !py-1.5 ml-auto text-footnote" @click="remove">
        {{ isPending ? '取消' : '移除' }}
      </button>
    </div>
  </div>
</template>
