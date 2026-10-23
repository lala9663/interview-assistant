<script setup lang="ts">
import { NotebookPenIcon, PlusIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import type { CandidateNote, SessionInterviewerView } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { formatTime } from '@/lib/time'

import { submitOnModEnter } from './transcript-utils'

const props = defineProps<{
  notes: CandidateNote[]
  panel: SessionInterviewerView[]
  /** Saves a note; resolves to true when stored (the box is cleared only then). */
  save: (content: string) => Promise<boolean>
  pending: boolean
}>()

const text = ref('')
const names = computed(() => new Map(props.panel.map((p) => [p.interviewer_id, p.interviewer.name])))
const newestFirst = computed(() => [...props.notes].reverse())

async function add() {
  const t = text.value.trim()
  if (!t) return
  if (await props.save(t)) text.value = ''
}
</script>

<template>
  <div class="space-y-3">
    <div class="space-y-2">
      <Textarea
        v-model="text"
        placeholder="관찰한 점을 기록하세요 (Ctrl+Enter). 메모는 작성자와 시각이 함께 저장됩니다."
        aria-label="면접관 메모"
        class="min-h-20 text-[13px]"
        @keydown="(e: KeyboardEvent) => submitOnModEnter(e, add)"
      />
      <div class="flex justify-end">
        <Button size="xs" variant="secondary" :disabled="pending || !text.trim()" @click="add">
          <PlusIcon />
          메모 추가
        </Button>
      </div>
    </div>
    <EmptyState v-if="notes.length === 0" compact :icon="NotebookPenIcon" title="메모가 없습니다" />
    <ol v-else class="space-y-2">
      <li v-for="n in newestFirst" :key="n.id" class="rounded-lg border bg-card p-3">
        <p class="text-[13px] leading-relaxed whitespace-pre-wrap">{{ n.content }}</p>
        <p class="mt-1.5 text-[11px] text-muted-foreground">{{ names.get(n.author_id) ?? '면접관' }} · {{ formatTime(n.created_at) }}</p>
      </li>
    </ol>
  </div>
</template>
