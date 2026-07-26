<script setup>
import { nextTick, ref, watch } from 'vue'
import AppSheet from './AppSheet.vue'
import { useTelegram } from '../composables/useTelegram.js'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'done'])

const { startLogin, verify, abortLogin, refresh } = useTelegram()

// The library reports Telegram's raw error codes. Translate the ones a user
// can actually act on; anything else passes through so nothing is hidden.
const ERROR_HINTS = [
  [/PHONE_NUMBER_INVALID/i, '手機號碼格式不正確，請含國碼，例如 +886912345678。'],
  [/PHONE_NUMBER_BANNED/i, '這個號碼已被 Telegram 停權。'],
  [/PHONE_CODE_INVALID/i, '驗證碼不正確，請再確認一次。'],
  [/PHONE_CODE_EXPIRED/i, '驗證碼已過期，請按「重新開始」重新索取。'],
  [/PASSWORD_HASH_INVALID|PASSWORD_INVALID/i, '兩步驟驗證密碼不正確。'],
  [/FLOOD_WAIT|flood wait/i, 'Telegram 暫時限制了登入嘗試，請過一段時間再試。'],
  [/SESSION_PASSWORD_NEEDED/i, '這個帳號需要兩步驟驗證密碼。'],
]

function humanize(message) {
  return ERROR_HINTS.find(([re]) => re.test(message))?.[1] || message
}

// phone -> code -> password -> done. One question on screen at a time: the
// user is copying a code out of another app and should not have to parse a
// form while doing it.
const step = ref('phone')
const phone = ref('')
const answer = ref('')
const busy = ref(false)
const error = ref('')
const account = ref('')
const input = ref(null)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    step.value = 'phone'
    phone.value = answer.value = error.value = account.value = ''
    focusInput()
  }
)

function focusInput() {
  nextTick(() => input.value?.focus())
}

function applyState(state) {
  if (state.stage === 'code' || state.stage === 'password') {
    step.value = state.stage
    answer.value = ''
    focusInput()
  } else if (state.stage === 'done') {
    account.value = state.account
    step.value = 'done'
    refresh()
    emit('done')
  } else {
    // "failed" and the odd "starting" that never advanced land here.
    error.value = humanize(state.error || '登入未完成，請重試')
  }
}

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    applyState(
      step.value === 'phone'
        ? await startLogin(phone.value.trim())
        : await verify(answer.value.trim())
    )
  } catch (e) {
    error.value = humanize(e.message)
  } finally {
    busy.value = false
  }
}

async function restart() {
  await abortLogin().catch(() => {})
  step.value = 'phone'
  answer.value = error.value = ''
  focusInput()
}

async function close() {
  if (step.value !== 'done') await abortLogin().catch(() => {})
  emit('close')
}
</script>

<template>
  <AppSheet
    :open="open"
    title="登入 Telegram"
    :dismiss-label="step === 'done' ? '完成' : '取消'"
    @close="close"
  >
    <form class="space-y-5" @submit.prevent="submit">
      <template v-if="step === 'phone'">
        <p class="text-subhead text-label-2">
          用你自己的 Telegram 帳號登入，之後就能下載你已加入的頻道裡的檔案。
        </p>
        <div>
          <label class="block text-footnote text-label-2 mb-1.5">手機號碼</label>
          <input
            ref="input"
            v-model="phone"
            type="tel"
            inputmode="tel"
            autocomplete="tel"
            required
            placeholder="+886912345678"
            class="field text-body tracking-wide"
          />
          <p class="text-footnote text-label-3 mt-1.5">
            請含國碼。Telegram 會傳一組驗證碼到你的其他裝置。
          </p>
        </div>
      </template>

      <template v-else-if="step === 'code'">
        <p class="text-subhead text-label-2">
          驗證碼已送到你的 Telegram（App 內訊息，不是簡訊）。
        </p>
        <div>
          <label class="block text-footnote text-label-2 mb-1.5">驗證碼</label>
          <input
            ref="input"
            v-model="answer"
            inputmode="numeric"
            autocomplete="one-time-code"
            required
            placeholder="12345"
            class="field text-center text-large font-semibold tracking-[0.4em]"
          />
        </div>
      </template>

      <template v-else-if="step === 'password'">
        <p class="text-subhead text-label-2">
          這個帳號開了兩步驟驗證，請輸入你的密碼。
        </p>
        <div>
          <label class="block text-footnote text-label-2 mb-1.5">兩步驟驗證密碼</label>
          <input
            ref="input"
            v-model="answer"
            type="password"
            autocomplete="current-password"
            required
            class="field text-body"
          />
          <p class="text-footnote text-label-3 mt-1.5">
            只用來完成這次登入，不會被儲存或寫進日誌。
          </p>
        </div>
      </template>

      <template v-else>
        <div class="text-center py-4">
          <div
            class="w-14 h-14 rounded-full bg-green/15 text-green mx-auto
                   flex items-center justify-center"
          >
            <svg viewBox="0 0 24 24" class="w-7 h-7" fill="none" stroke="currentColor"
                 stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 12.5 9.5 18 20 6.5" />
            </svg>
          </div>
          <p class="text-title3 font-semibold mt-4">已登入</p>
          <p class="text-subhead text-label-2 mt-1">{{ account }}</p>
          <p class="text-footnote text-label-3 mt-4">
            接著在正式的 Telegram App 加入你要抓的頻道，再回來貼上貼文連結。
          </p>
        </div>
      </template>

      <p
        v-if="error"
        class="text-subhead text-red bg-red/10 rounded-[0.75rem] px-3.5 py-2.5"
      >
        {{ error }}
      </p>

      <div v-if="step !== 'done'" class="flex items-center gap-3">
        <button type="submit" class="btn btn-filled flex-1" :disabled="busy">
          {{ busy ? '處理中…' : step === 'phone' ? '傳送驗證碼' : '確認' }}
        </button>
        <button
          v-if="step !== 'phone'"
          type="button"
          class="btn btn-plain"
          @click="restart"
        >
          重新開始
        </button>
      </div>
    </form>
  </AppSheet>
</template>
