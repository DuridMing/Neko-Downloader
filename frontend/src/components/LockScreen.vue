<script setup>
import { onMounted, ref } from 'vue'
import { unlock } from '../composables/useApi.js'

const password = ref('')
const busy = ref(false)
const error = ref('')
const input = ref(null)

onMounted(() => input.value?.focus())

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await unlock(password.value)
  } catch (e) {
    error.value = e.message
    password.value = ''
    input.value?.focus()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center px-5">
    <form class="card w-full max-w-[22rem] p-7 text-center" @submit.prevent="submit">
      <div
        class="w-14 h-14 rounded-full bg-fill text-label-2 mx-auto flex items-center justify-center"
      >
        <svg viewBox="0 0 24 24" class="w-6 h-6" fill="none" stroke="currentColor"
             stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="4.5" y="10.5" width="15" height="10" rx="3" />
          <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
        </svg>
      </div>

      <h1 class="text-title3 font-semibold mt-4">🐱 Neko Downloader</h1>
      <p class="text-footnote text-label-2 mt-1">請輸入存取密碼</p>

      <input
        ref="input"
        v-model="password"
        type="password"
        autocomplete="current-password"
        required
        class="field text-body text-center mt-5"
      />

      <p v-if="error" class="text-footnote text-red mt-2">{{ error }}</p>

      <button type="submit" class="btn btn-filled w-full mt-4" :disabled="busy">
        {{ busy ? '確認中…' : '解鎖' }}
      </button>
    </form>
  </div>
</template>
