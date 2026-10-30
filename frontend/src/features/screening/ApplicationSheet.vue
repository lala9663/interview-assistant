<script setup lang="ts">
import { ChevronLeftIcon, ChevronRightIcon } from '@lucide/vue'
import { onScopeDispose, ref, watch } from 'vue'

import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Sheet, SheetContent } from '@/components/ui/sheet'

import ApplicationDetail from './ApplicationDetail.vue'

/** `prevId`/`nextId` follow the list as it is filtered and sorted; ←/→ move too. */
const props = defineProps<{
  applicationId: string | null
  postingId: string
  prevId?: string | null
  nextId?: string | null
  position?: { index: number; total: number } | null
}>()
const emit = defineEmits<{ close: []; navigate: [applicationId: string] }>()

// Keep the last application on screen while the sheet slides out.
const shownId = ref(props.applicationId)
watch(
  () => props.applicationId,
  (id) => {
    if (id) shownId.value = id
  },
)

// Arrow keys belong to whatever has focus when it uses them: text fields, the status switch
// (a radio group), tabs, menus, sliders.
const KEEPS_ARROWS = 'input, textarea, select, [contenteditable], [role="radiogroup"], [role="tablist"], [role="menu"], [role="listbox"], [role="slider"], [role="combobox"]'

function onKey(e: KeyboardEvent) {
  if (!props.applicationId || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  if (e.target instanceof Element && e.target.closest(KEEPS_ARROWS)) return
  // Another dialog over the sheet (탈락 사유, 면접 잡기) keeps the keys.
  if (document.querySelectorAll('[role="dialog"], [role="alertdialog"]').length > 1) return
  const id = e.key === 'ArrowLeft' ? props.prevId : props.nextId
  if (!id) return
  e.preventDefault()
  emit('navigate', id)
}
window.addEventListener('keydown', onKey)
onScopeDispose(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Sheet :open="applicationId !== null" @update:open="(o) => !o && emit('close')">
    <SheetContent class="overflow-y-auto scrollbar-thin">
      <nav v-if="position" class="-mb-3 flex items-center gap-1 px-6 pt-4 text-xs text-muted-foreground" aria-label="지원자 이동" data-testid="sheet-nav">
        <Button variant="ghost" size="icon-xs" aria-label="이전 지원자" :disabled="!prevId" @click="prevId && emit('navigate', prevId)">
          <ChevronLeftIcon />
        </Button>
        <Button variant="ghost" size="icon-xs" aria-label="다음 지원자" :disabled="!nextId" @click="nextId && emit('navigate', nextId)">
          <ChevronRightIcon />
        </Button>
        <span class="ml-1 tabular">{{ position.index }} / {{ position.total }}</span>
        <span class="ml-2 hidden items-center gap-1 sm:inline-flex" aria-hidden="true"><Kbd>←</Kbd><Kbd>→</Kbd></span>
      </nav>
      <ApplicationDetail v-if="shownId" :key="shownId" :application-id="shownId" :posting-id="postingId" />
    </SheetContent>
  </Sheet>
</template>
