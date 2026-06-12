import { reactive, ref } from 'vue'

const jobs = reactive(new Map())
const connected = ref(false)
let ws = null
let retryDelay = 1000

async function refreshSnapshot() {
  try {
    const res = await fetch('/api/jobs')
    const list = await res.json()
    jobs.clear()
    for (const job of list) jobs.set(job.id, job)
  } catch {
    /* backend unreachable; the WS retry loop will recover */
  }
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${proto}//${location.host}/ws`)

  ws.onopen = () => {
    connected.value = true
    retryDelay = 1000
  }

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.type === 'queue_snapshot') {
      jobs.clear()
      for (const job of msg.jobs) jobs.set(job.id, job)
    } else if (msg.type === 'job_update') {
      jobs.set(msg.job.id, msg.job)
    } else if (msg.type === 'job_removed') {
      jobs.delete(msg.id)
    }
  }

  ws.onclose = () => {
    connected.value = false
    setTimeout(() => {
      refreshSnapshot()
      connect()
    }, retryDelay)
    retryDelay = Math.min(retryDelay * 2, 15000)
  }
}

let started = false

export function useWebSocket() {
  if (!started) {
    started = true
    connect()
  }
  return { jobs, connected }
}
