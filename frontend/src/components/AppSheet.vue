<script>
// Module scope, so every AppSheet instance shares it: this is the stack of
// currently-open sheets, top last.
const stack = []
</script>

<script setup>
import { onBeforeUnmount, watch } from 'vue'

// A sheet, the way the platform does it: a card over dimmed, blurred content
// on a large screen; anchored to the bottom edge on a phone. Dismissed by
// Escape, by the backdrop, or by the trailing button in its own header.
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  dismissLabel: { type: String, default: '完成' },
})
const emit = defineEmits(['close'])

// Telegram verification opens on top of settings, so the scroll lock and
// Escape are tracked across the whole stack: releasing them when the top sheet
// closes would unlock a page that still has a sheet over it, and a per-sheet
// key listener would close the entire stack with one Escape.
function lock() {
  stack.push(onKey)
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', onKey)
}

function unlock() {
  const i = stack.indexOf(onKey)
  if (i !== -1) stack.splice(i, 1)
  window.removeEventListener('keydown', onKey)
  if (!stack.length) document.body.style.overflow = ''
}

function onKey(e) {
  // Only the topmost sheet reacts.
  if (e.key === 'Escape' && stack[stack.length - 1] === onKey) emit('close')
}

watch(() => props.open, (open) => (open ? lock() : unlock()))

onBeforeUnmount(unlock)
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-end sm:items-center justify-center sm:p-6"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
      >
        <div
          class="sheet-scrim absolute inset-0 backdrop-blur-md"
          @click="emit('close')"
        ></div>

        <div
          class="sheet-card relative w-full sm:max-w-[30rem] max-h-[92vh] overflow-y-auto
                 bg-card rounded-t-[1.25rem] sm:rounded-[1.25rem]"
        >
          <!-- Grabber: the affordance a bottom sheet is expected to have. -->
          <div class="sm:hidden flex justify-center pt-2.5">
            <div class="w-9 h-1 rounded-full bg-label-3"></div>
          </div>

          <header
            class="sticky top-0 z-10 bg-material backdrop-blur-xl
                   flex items-center justify-between gap-4 px-5 py-3.5
                   border-b border-separator"
          >
            <h2 class="text-[1.0625rem] font-semibold truncate">{{ title }}</h2>
            <button class="btn btn-plain -mr-2" @click="emit('close')">
              {{ dismissLabel }}
            </button>
          </header>

          <div class="px-5 py-5">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sheet-scrim {
  background: var(--c-scrim);
}
.sheet-card {
  box-shadow: var(--shadow-sheet);
}

.sheet-enter-active,
.sheet-leave-active {
  transition: opacity 0.35s var(--ease-sheet);
}
.sheet-enter-active .sheet-card,
.sheet-leave-active .sheet-card {
  transition: transform 0.4s var(--ease-sheet);
}
.sheet-enter-from,
.sheet-leave-to {
  opacity: 0;
}
/* Up from the edge on a phone, forward from behind on a desktop. */
.sheet-enter-from .sheet-card,
.sheet-leave-to .sheet-card {
  transform: translateY(28px) scale(0.98);
}
</style>
