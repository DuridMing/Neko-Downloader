<script setup>
import { computed, ref, watch } from 'vue'
import AppSheet from './AppSheet.vue'
import TelegramLoginSheet from './TelegramLoginSheet.vue'
import { useTelegram } from '../composables/useTelegram.js'
import { useCookies } from '../composables/useCookies.js'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close'])

const { status, refresh, deleteSession } = useTelegram()
const { cookies, clear: clearCookies } = useCookies()

const loginOpen = ref(false)
const confirmingDelete = ref(false)
const busy = ref(false)
const error = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    confirmingDelete.value = false
    error.value = ''
    refresh()
  }
)

// One sentence that says exactly which of the four states we are in, because
// "Telegram doesn't work" has four very different fixes.
const telegram = computed(() => {
  if (!status.loaded) return { tint: 'text-label-3', title: '檢查中…', detail: '' }
  if (!status.available)
    return {
      tint: 'text-label-3',
      title: '未安裝',
      detail: '伺服器缺少 kurigram 套件，請重新安裝相依套件後重啟。',
    }
  if (!status.configured)
    return {
      tint: 'text-orange',
      title: '未設定 API 憑證',
      detail:
        '請到 my.telegram.org/apps 申請，把 TELEGRAM_API_ID 與 TELEGRAM_API_HASH 寫進伺服器的 .env 後重啟。',
    }
  if (status.account)
    return { tint: 'text-label', title: status.account, detail: '已登入，可下載你已加入頻道裡的檔案。' }
  if (status.has_session && status.error)
    return { tint: 'text-red', title: '登入已失效', detail: status.error }
  if (status.has_session)
    return { tint: 'text-label', title: '已登入', detail: '這台伺服器上已有可用的登入資料。' }
  return { tint: 'text-label', title: '未登入', detail: '登入後即可下載 t.me 貼文連結裡的影片。' }
})

async function removeSession() {
  busy.value = true
  error.value = ''
  try {
    await deleteSession()
    confirmingDelete.value = false
    await refresh()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AppSheet :open="open" title="設定" @close="emit('close')">
    <div class="space-y-7">
      <!-- Telegram -->
      <section>
        <h3 class="text-footnote font-semibold text-label-2 uppercase tracking-wide px-1 mb-2">
          Telegram 帳號
        </h3>
        <div class="rounded-[0.875rem] bg-card-2 overflow-hidden">
          <div class="flex items-center gap-3.5 px-4 py-3.5">
            <span
              class="shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
              :class="status.account || status.has_session
                ? 'bg-green/15 text-green'
                : 'bg-fill text-label-2'"
            >
              <svg viewBox="0 0 24 24" class="w-5 h-5" fill="currentColor">
                <path d="M21.7 3.4 2.9 10.6c-.9.4-.9 1.6 0 1.9l4.6 1.5 1.8 5.4c.2.7 1.1.9 1.6.3l2.5-2.7 4.7 3.5c.6.4 1.4.1 1.6-.6l3.1-15c.2-.8-.6-1.5-1.1-1.5Z" />
              </svg>
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-subhead font-medium truncate" :class="telegram.tint">
                {{ telegram.title }}
              </p>
              <p class="text-footnote text-label-2 mt-0.5">{{ telegram.detail }}</p>
            </div>
          </div>

          <div
            v-if="status.available && status.configured"
            class="border-t border-separator px-4 py-3 flex items-center gap-3"
          >
            <template v-if="confirmingDelete">
              <p class="text-footnote text-label-2 flex-1">
                會向 Telegram 撤銷這組登入並刪除伺服器上的 session 檔。
              </p>
              <button class="btn btn-plain !text-red" :disabled="busy" @click="removeSession">
                {{ busy ? '刪除中…' : '確定刪除' }}
              </button>
              <button class="btn btn-plain" @click="confirmingDelete = false">取消</button>
            </template>
            <template v-else>
              <button
                class="btn btn-tinted"
                @click="loginOpen = true"
              >
                {{ status.has_session ? '重新登入' : '登入 Telegram' }}
              </button>
              <button
                v-if="status.has_session"
                class="btn btn-plain !text-red ml-auto"
                @click="confirmingDelete = true"
              >
                刪除登入資料
              </button>
            </template>
          </div>
        </div>
        <p v-if="error" class="text-footnote text-red mt-2 px-1">{{ error }}</p>
        <p class="text-footnote text-label-3 mt-2 px-1">
          登入資料只留在伺服器上（權限 600），不會出現在日誌或 API 回應裡。頻道要自己在正式的
          Telegram App 加入，本工具不會替你加入任何頻道。
        </p>
      </section>

      <!-- Cookies -->
      <section>
        <h3 class="text-footnote font-semibold text-label-2 uppercase tracking-wide px-1 mb-2">
          網站 Cookie
        </h3>
        <div class="rounded-[0.875rem] bg-card-2 px-4 py-3.5 flex items-center gap-3">
          <div class="min-w-0 flex-1">
            <p class="text-subhead font-medium">
              {{ cookies ? '已存放於這個分頁' : '未設定' }}
            </p>
            <p class="text-footnote text-label-2 mt-0.5">
              抓需要登入的網站時才需要。關閉分頁即消失，伺服器用完即刪。
            </p>
          </div>
          <button v-if="cookies" class="btn btn-plain !text-red" @click="clearCookies">
            清除
          </button>
        </div>
      </section>

      <!-- About -->
      <section>
        <h3 class="text-footnote font-semibold text-label-2 uppercase tracking-wide px-1 mb-2">
          關於
        </h3>
        <div class="rounded-[0.875rem] bg-card-2 px-4 py-3.5 space-y-1">
          <p class="text-footnote text-label-2">
            檔案只暫存在伺服器磁碟，取走、逾時或服務重啟後立即刪除。
          </p>
          <p class="text-footnote text-label-3">
            內部工具 · 無帳號系統，請勿暴露於公開網路。
          </p>
        </div>
      </section>
    </div>
  </AppSheet>

  <TelegramLoginSheet :open="loginOpen" @close="loginOpen = false" @done="refresh" />
</template>
