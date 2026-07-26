<script setup>
import { onMounted, ref } from 'vue'
import UrlForm from './components/UrlForm.vue'
import QueueList from './components/QueueList.vue'
import SettingsSheet from './components/SettingsSheet.vue'
import LockScreen from './components/LockScreen.vue'
import { useWebSocket } from './composables/useWebSocket.js'
import { useTelegram } from './composables/useTelegram.js'
import { locked } from './composables/useApi.js'

const { connected } = useWebSocket()
const { refresh } = useTelegram()
const settingsOpen = ref(false)

// Doubles as the lock probe: a 401 here flips `locked` before anything renders.
onMounted(refresh)
</script>

<template>
  <LockScreen v-if="locked" />

  <div v-else class="min-h-screen">
    <header
      class="sticky top-0 z-30 bg-material backdrop-blur-xl border-b border-separator"
    >
      <div class="max-w-2xl mx-auto px-5 h-14 flex items-center justify-between gap-4">
        <h1 class="text-[1.0625rem] font-semibold tracking-tight">🐱 Neko Downloader</h1>

        <div class="flex items-center gap-1.5">
          <!-- Connection state earns colour only when it is bad news. -->
          <span
            class="flex items-center gap-1.5 text-footnote pr-1"
            :class="connected ? 'text-label-3' : 'text-orange'"
          >
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="connected ? 'bg-green' : 'bg-orange animate-pulse'"
            ></span>
            <span class="hidden sm:inline">{{ connected ? '已連線' : '連線中斷' }}</span>
          </span>

          <button
            class="w-9 h-9 rounded-full flex items-center justify-center
                   text-label-2 hover:bg-fill transition-colors"
            aria-label="設定"
            @click="settingsOpen = true"
          >
            <svg viewBox="0 0 24 24" class="w-5 h-5" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="3.2" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.7 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34H9.1a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.08a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.56 1.03Z" />
            </svg>
          </button>
        </div>
      </div>
    </header>

    <main class="max-w-2xl mx-auto px-5 pt-10 pb-16 space-y-9">
      <div>
        <h2 class="text-large font-bold tracking-tight leading-tight">貼上連結就好</h2>
        <p class="text-subhead text-label-2 mt-1.5">
          串流、影音平台、一般網頁，還有你已加入的 Telegram 頻道 —— 系統會自己判斷怎麼抓。
        </p>
      </div>

      <UrlForm @open-settings="settingsOpen = true" />
      <QueueList />
    </main>

    <footer class="max-w-2xl mx-auto px-5 pb-10 text-center text-footnote text-label-3">
      內部工具 · 檔案取走或逾時後自動刪除，伺服器不長期保存
    </footer>

    <SettingsSheet :open="settingsOpen" @close="settingsOpen = false" />
  </div>
</template>
