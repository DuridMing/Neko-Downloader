import { ref, watch } from 'vue'

// sessionStorage, never localStorage: the cookie a user pastes is a live
// credential and must die with the tab. Shared so the form and the settings
// panel are looking at the same value.
const KEY = 'neko.cookies'
const cookies = ref(sessionStorage.getItem(KEY) || '')

watch(cookies, (value) => {
  if (value) sessionStorage.setItem(KEY, value)
  else sessionStorage.removeItem(KEY)
})

export function useCookies() {
  return { cookies, clear: () => (cookies.value = '') }
}
