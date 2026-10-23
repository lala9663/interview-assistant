<script setup lang="ts">
import { CheckIcon, CornerDownLeftIcon, ListChecksIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { PresetQuestion, QAItem } from '@/api/types'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const props = defineProps<{ presets: PresetQuestion[]; qaItems: QAItem[]; disabled: boolean; pendingId: string | null }>()
const emit = defineEmits<{ ask: [preset: PresetQuestion] }>()

const askedSeq = computed(() => {
  const m = new Map<string, number>()
  for (const q of props.qaItems) {
    if (q.question_source !== 'preset') continue
    const p = props.presets.find((x) => x.question === q.question)
    if (p) m.set(p.id, q.seq)
  }
  return m
})
const groups = computed(() => {
  const m = new Map<string, PresetQuestion[]>()
  for (const p of props.presets) m.set(p.competency, [...(m.get(p.competency) ?? []), p])
  return [...m.entries()]
})
</script>

<template>
  <section aria-label="사전 질문" class="space-y-3">
    <div class="flex items-center justify-between">
      <h3 class="flex items-center gap-1.5 text-[13px] font-semibold">
        <ListChecksIcon class="size-4 text-muted-foreground" aria-hidden="true" />
        사전 질문
      </h3>
      <span class="text-xs text-muted-foreground tabular">{{ askedSeq.size }}/{{ presets.length }}</span>
    </div>
    <p v-if="presets.length === 0" class="text-[13px] text-muted-foreground">이 공고에는 사전 질문 세트가 없습니다. 직접 질문을 입력하세요.</p>
    <div v-for="[competency, list] in groups" :key="competency" class="space-y-1.5">
      <p class="text-[11.5px] font-medium text-muted-foreground">{{ competency }}</p>
      <div
        v-for="p in list"
        :key="p.id"
        :class="cn('group rounded-lg border bg-card p-2.5 transition-colors', askedSeq.get(p.id) ? 'border-transparent bg-subtle' : 'hover:border-foreground/15')"
      >
        <p :class="cn('text-[12.5px] leading-snug', askedSeq.get(p.id) && 'text-muted-foreground')">{{ p.question }}</p>
        <div class="mt-2 flex items-center justify-between gap-2">
          <span class="truncate text-[11px] text-muted-foreground">{{ p.intent }}</span>
          <span v-if="askedSeq.get(p.id)" class="inline-flex items-center gap-1 text-[11.5px] font-medium text-success">
            <CheckIcon class="size-3.5" aria-hidden="true" />Q{{ askedSeq.get(p.id) }}
          </span>
          <Button
            v-else
            size="xs"
            variant="outline"
            :disabled="disabled || pendingId !== null"
            :aria-label="`사전 질문 기록: ${p.question}`"
            @click="emit('ask', p)"
          >
            <CornerDownLeftIcon />
            {{ pendingId === p.id ? '기록 중…' : '질문하기' }}
          </Button>
        </div>
      </div>
    </div>
  </section>
</template>
