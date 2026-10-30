<script setup lang="ts">
import { ChevronDownIcon, NotebookPenIcon, PlusIcon } from '@lucide/vue'
import { computed, ref, useId } from 'vue'

import type { CandidateNote, SessionInterviewerView } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { formatTime } from '@/lib/time'
import { cn } from '@/lib/utils'

import { blurOnEscape, submitOnModEnter } from './transcript-utils'

/** The room's notes, kept at the foot of the right column: the box always at hand, earlier notes folded. */
const props = defineProps<{
  notes: CandidateNote[]
  panel: SessionInterviewerView[]
  /** Saves a note; resolves to true when stored (the box is cleared only then). */
  save: (content: string) => Promise<boolean>
  pending: boolean
}>()

const text = ref('')
const listOpen = ref(false)
const listId = useId()
const names = computed(() => new Map(props.panel.map((p) => [p.interviewer_id, p.interviewer.name])))
const newestFirst = computed(() => [...props.notes].reverse())

async function add() {
  const t = text.value.trim()
  if (!t) return
  if (await props.save(t)) text.value = ''
}
const onKey = (e: KeyboardEvent) => {
  blurOnEscape(e)
  submitOnModEnter(e, add)
}
</script>

<template>
  <section aria-label="메모" class="space-y-2">
    <div class="flex items-center justify-between gap-2">
      <h3 class="flex items-center gap-1.5 text-[13px] font-semibold">
        <NotebookPenIcon class="size-4 text-muted-foreground" aria-hidden="true" />
        메모
        <span class="font-normal text-muted-foreground tabular">{{ notes.length }}</span>
      </h3>
      <Button v-if="notes.length > 0" size="xs" variant="ghost" :aria-expanded="listOpen" :aria-controls="listId" @click="listOpen = !listOpen">
        <ChevronDownIcon :class="cn('transition-transform', listOpen && 'rotate-180')" />
        {{ listOpen ? '접기' : '지난 메모 보기' }}
      </Button>
    </div>
    <ol v-if="listOpen" :id="listId" class="max-h-48 space-y-2 overflow-y-auto scrollbar-thin" aria-label="지난 메모">
      <li v-for="n in newestFirst" :key="n.id" class="rounded-lg border bg-card p-2.5">
        <p class="text-[13px] leading-relaxed whitespace-pre-wrap">{{ n.content }}</p>
        <p class="mt-1 text-[11px] text-muted-foreground">{{ names.get(n.author_id) ?? '면접관' }} · {{ formatTime(n.created_at) }}</p>
      </li>
    </ol>
    <div class="flex items-end gap-2">
      <Textarea
        v-model="text"
        placeholder="관찰한 점 (Ctrl+Enter 추가)"
        title="작성자와 시각이 함께 저장됩니다"
        aria-label="면접관 메모"
        class="max-h-32 min-h-14 flex-1 text-[13px] [field-sizing:content]"
        @keydown="onKey"
      />
      <Button size="xs" variant="secondary" :disabled="pending || !text.trim()" @click="add">
        <PlusIcon />
        메모 추가
      </Button>
    </div>
  </section>
</template>
