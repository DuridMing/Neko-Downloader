import { reactive } from 'vue'
import { request } from './useApi.js'

// One shared status object: the header badge, the settings panel and the URL
// form all ask the same question ("is Telegram usable, and as whom?").
const status = reactive({
  loaded: false,
  available: false, // the library is installed
  configured: false, // api_id / api_hash are set
  has_session: false,
  account: null,
  error: null,
})

async function refresh() {
  try {
    Object.assign(status, await request('/api/telegram'), { loaded: true })
  } catch {
    status.loaded = true // backend unreachable or locked; the UI says so itself
  }
  return status
}

export function useTelegram() {
  return {
    status,
    refresh,
    startLogin: (phone) =>
      request('/api/telegram/login', {
        method: 'POST',
        body: JSON.stringify({ phone }),
      }),
    verify: (answer) =>
      request('/api/telegram/login/verify', {
        method: 'POST',
        body: JSON.stringify({ answer }),
      }),
    abortLogin: () => request('/api/telegram/login', { method: 'DELETE' }),
    deleteSession: () => request('/api/telegram/session', { method: 'DELETE' }),
  }
}
