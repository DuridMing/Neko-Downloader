<script setup>
import { computed, ref } from 'vue'
import { request } from '../composables/useApi.js'
import { useCookies } from '../composables/useCookies.js'
import { useTelegram } from '../composables/useTelegram.js'

const emit = defineEmits(['open-settings'])

const { cookies, clear: clearCookies } = useCookies()
const { status: telegram } = useTelegram()

const url = ref('')
const referer = ref('')
const showAdvanced = ref(Boolean(cookies.value))
const submitting = ref(false)
const error = ref('')

// Catch the one mistake this UI can predict: a Telegram link with nobody
// logged in. Say it before the job fails, next to the field that caused it.
const needsTelegramLogin = computed(() => {
  const value = url.value.trim()
  if (!/^https?:\/\/(www\.)?t(elegram)?\.me\//i.test(value)) return false
  return telegram.loaded && !telegram.has_session
})

async function submit() {
  if (!url.value.trim() || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    await request('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({
        url: url.value.trim(),
        referer: referer.value.trim() || null,
        cookies: cookies.value.trim() || null,
      }),
    })
    url.value = ''
  } catch (e) {
    error.value = `提交失敗：${e.message}`
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="card p-5">
    <form class="space-y-3.5" @submit.prevent="submit">
      <div class="flex flex-col sm:flex-row gap-2.5">
        <input
          v-model="url"
          type="url"
          required
          placeholder="https://… 或 t.me/頻道/貼文編號"
          class="field flex-1 text-body"
        />
        <button type="submit" class="btn btn-filled sm:px-7" :disabled="submitting">
          {{ submitting ? '提交中…' : '下載' }}
        </button>
      </div>

      <div
        v-if="needsTelegramLogin"
        class="flex items-center gap-3 rounded-[0.75rem] bg-accent-fill px-3.5 py-2.5"
      >
        <p class="text-footnote text-label flex-1">
          這是 Telegram 連結，需要先登入你的 Telegram 帳號。
        </p>
        <button type="button" class="btn btn-plain !py-0" @click="emit('open-settings')">
          去登入
        </button>
      </div>

      <button
        type="button"
        class="flex items-center gap-1 text-footnote text-label-2 hover:text-label transition-colors"
        @click="showAdvanced = !showAdvanced"
      >
        <svg
          viewBox="0 0 24 24" class="w-3.5 h-3.5 transition-transform duration-200"
          :class="{ 'rotate-90': showAdvanced }"
          fill="none" stroke="currentColor" stroke-width="2.5"
          stroke-linecap="round" stroke-linejoin="round"
        >
          <path d="m9 5 7 7-7 7" />
        </svg>
        進階選項
        <span v-if="cookies" class="text-accent">· 已設定 Cookie</span>
      </button>

      <Transition name="reveal">
        <div v-if="showAdvanced" class="space-y-4 pt-1">
          <div>
            <label class="block text-footnote text-label-2 mb-1.5">
              自訂 Referer（選填，預設自動推導）
            </label>
            <input v-model="referer" type="url" placeholder="https://example.com/watch" class="field" />
          </div>

          <div>
            <div class="flex items-center justify-between mb-1.5">
              <label class="text-footnote text-label-2">
                Cookie（選填，抓需要登入的網站用）
              </label>
              <button
                v-if="cookies"
                type="button"
                class="text-footnote text-red"
                @click="clearCookies"
              >
                清除
              </button>
            </div>
            <textarea
              v-model="cookies"
              rows="3"
              spellcheck="false"
              placeholder="sessionid=abc123; other=xyz（或 Netscape 格式）"
              class="field font-mono text-footnote resize-y"
            ></textarea>
            <p class="text-footnote text-label-3 mt-1.5">
              只留在這個分頁，關閉即消失；伺服器用完即刪，不寫進日誌。
            </p>
          </div>
        </div>
      </Transition>

      <p v-if="error" class="text-subhead text-red">{{ error }}</p>
    </form>
  </section>
</template>

<style scoped>
.reveal-enter-active,
.reveal-leave-active {
  transition: opacity 0.25s var(--ease-sheet), transform 0.25s var(--ease-sheet);
}
.reveal-enter-from,
.reveal-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
