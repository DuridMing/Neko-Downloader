import { ref } from 'vue'

// Every 401 means the same thing: the shared password is enabled and this
// browser has not passed it. One place to notice it, one screen to react.
export const locked = ref(false)

export async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = await res.json().catch(() => ({}))
  if (res.status === 401) locked.value = true
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
  return body
}

export async function unlock(password) {
  await request('/api/unlock', {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
  // Reload rather than unwind the locked state by hand: the websocket, the
  // queue snapshot and the Telegram status all need re-fetching anyway.
  location.reload()
}
