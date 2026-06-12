<script setup>
import { ref, onMounted, watch } from 'vue'

const COOKIES_KEY = 'neko.cookies'

const url = ref('')
const referer = ref('')
const cookies = ref('')
const showAdvanced = ref(false)
const submitting = ref(false)
const error = ref('')

// Cookies live only in this browser tab (sessionStorage) and are wiped when
// the tab/browser closes. They are never persisted to disk on the client.
onMounted(() => {
  cookies.value = sessionStorage.getItem(COOKIES_KEY) || ''
  if (cookies.value) showAdvanced.value = true
})

watch(cookies, (v) => {
  if (v) sessionStorage.setItem(COOKIES_KEY, v)
  else sessionStorage.removeItem(COOKIES_KEY)
})

function clearCookies() {
  cookies.value = ''
}

async function submit() {
  if (!url.value.trim() || submitting.value) return
  submitting.value = true
  error.value = ''
  try {
    const res = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: url.value.trim(),
        referer: referer.value.trim() || null,
        cookies: cookies.value.trim() || null,
      }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${res.status}`)
    }
    url.value = ''
  } catch (e) {
    error.value = `提交失敗：${e.message}`
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="bg-panel border border-edge rounded-2xl p-6 shadow-lg">
    <h2 class="text-sm font-medium text-gray-400 mb-3">貼上影片連結，系統會自動判斷下載方式</h2>
    <form @submit.prevent="submit" class="space-y-3">
      <div class="flex gap-3">
        <input
          v-model="url"
          type="url"
          required
          placeholder="https://example.com/video.m3u8 或任何平台影片頁連結"
          class="flex-1 bg-surface border border-edge rounded-xl px-4 py-3 text-sm
                 placeholder-gray-600 focus:outline-none focus:border-accent transition-colors"
        />
        <button
          type="submit"
          :disabled="submitting"
          class="bg-accent hover:bg-accent-soft disabled:opacity-50 text-white font-medium
                 px-6 py-3 rounded-xl text-sm transition-colors whitespace-nowrap"
        >
          {{ submitting ? '提交中…' : '下載' }}
        </button>
      </div>

      <button
        type="button"
        @click="showAdvanced = !showAdvanced"
        class="text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        {{ showAdvanced ? '▾' : '▸' }} 進階選項
        <span v-if="cookies" class="ml-1 text-accent-soft">· 已設定 Cookie</span>
      </button>

      <div v-if="showAdvanced" class="space-y-4 pt-1">
        <input
          v-model="referer"
          type="url"
          placeholder="自訂 Referer（選填，預設自動推導）"
          class="w-full bg-surface border border-edge rounded-xl px-4 py-2.5 text-sm
                 placeholder-gray-600 focus:outline-none focus:border-accent transition-colors"
        />

        <div>
          <div class="flex items-center justify-between mb-1.5">
            <label class="text-xs text-gray-400">
              Cookie（選填，抓需要登入的內容用）
            </label>
            <button
              v-if="cookies"
              type="button"
              @click="clearCookies"
              class="text-xs text-gray-500 hover:text-rose-400 transition-colors"
            >
              清除
            </button>
          </div>
          <textarea
            v-model="cookies"
            rows="3"
            spellcheck="false"
            placeholder="貼上 cookie，例如 sessionid=abc123; other=xyz（或 Netscape 格式）"
            class="w-full bg-surface border border-edge rounded-xl px-4 py-2.5 text-sm font-mono
                   placeholder-gray-600 focus:outline-none focus:border-accent transition-colors
                   resize-y"
          ></textarea>
          <p class="text-xs text-gray-600 mt-1.5 flex items-center gap-1.5">
            <span class="text-emerald-500">🔒</span>
            只保存在這個瀏覽器分頁，關閉後自動清除；送出下載後伺服器用完即刪，不留存。
          </p>
        </div>
      </div>

      <p v-if="error" class="text-sm text-rose-400">{{ error }}</p>
    </form>
  </section>
</template>
