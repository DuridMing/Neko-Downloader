<script setup>
import UrlForm from './components/UrlForm.vue'
import QueueList from './components/QueueList.vue'
import { useWebSocket } from './composables/useWebSocket.js'

const { connected } = useWebSocket()
</script>

<template>
  <div class="min-h-screen">
    <header class="border-b border-edge bg-panel/60 backdrop-blur sticky top-0 z-10">
      <div class="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
        <h1 class="text-xl font-bold tracking-tight">
          <span class="text-accent-soft">🐱 Neko</span> Downloader
        </h1>
        <span
          class="flex items-center gap-2 text-xs"
          :class="connected ? 'text-emerald-400' : 'text-rose-400'"
        >
          <span
            class="w-2 h-2 rounded-full"
            :class="connected ? 'bg-emerald-400' : 'bg-rose-400 animate-pulse'"
          ></span>
          {{ connected ? '已連線' : '連線中斷' }}
        </span>
      </div>
    </header>

    <main class="max-w-3xl mx-auto px-6 py-10 space-y-10">
      <UrlForm />
      <QueueList />
    </main>

    <footer class="max-w-3xl mx-auto px-6 pb-8 text-center text-xs text-gray-600">
      內部工具 · 檔案暫存於記憶體，下載後或 1 小時後自動清除
    </footer>
  </div>
</template>
