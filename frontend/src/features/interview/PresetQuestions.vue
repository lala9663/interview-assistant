<script setup lang="ts">
import { CheckIcon, CornerDownLeftIcon, ListChecksIcon, QuoteIcon, SparklesIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { PresetQuestion, QAItem } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * 사전 질문 of the session's round, and in round 2 and later the 이어 질문: AI questions for this
 * candidate built on the earlier round's answers (never one it already asked). Neither is asked
 * until the interviewer picks it.
 */
const props = withDefaults(
  defineProps<{
    presets: PresetQuestion[]
    qaItems: QAItem[]
    disabled: boolean
    pendingId: string | null
    carryover?: PresetQuestion[]
    /** the earlier round's label ("1차") when there is one to carry over from */
    earlierLabel?: string | null
    generating?: boolean
  }>(),
  { carryover: () => [], earlierLabel: null, generating: false },
)
const emit = defineEmits<{ ask: [preset: PresetQuestion]; generate: [] }>()

const askedSeq = computed(() => {
  const m = new Map<string, number>()
  for (const q of props.qaItems) {
    if (q.question_source !== 'preset') continue
    const p = [...props.presets, ...props.carryover].find((x) => x.question === q.question)
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
  <section v-if="earlierLabel" aria-label="이어 질문" class="space-y-2" data-testid="carryover">
    <div class="flex items-center justify-between gap-2">
      <h3 class="flex items-center gap-1.5 text-[13px] font-semibold">
        <SparklesIcon class="size-4 text-brand" aria-hidden="true" />
        이어 질문
        <span class="text-[11.5px] font-normal text-muted-foreground">{{ earlierLabel }} 답변 기반 · AI</span>
      </h3>
      <Button size="xs" variant="brand" :disabled="generating" @click="emit('generate')">
        {{ generating ? '만드는 중…' : carryover.length > 0 ? '다시 만들기' : '만들기' }}
      </Button>
    </div>
    <p v-if="carryover.length === 0" class="text-[12.5px] leading-relaxed text-muted-foreground">
      {{ earlierLabel }}에서 이미 물은 것은 반복하지 않고, 답변에서 덜 드러난 부분을 더 깊이 묻는 질문을 AI가 제안합니다.
    </p>
    <div
      v-for="p in carryover"
      :key="p.id"
      :class="cn('rounded-lg border bg-card p-2.5 transition-colors', askedSeq.get(p.id) ? 'border-transparent bg-subtle' : 'border-brand-border hover:border-ring')"
    >
      <p :class="cn('text-[12.5px] leading-snug', askedSeq.get(p.id) && 'text-muted-foreground')">{{ p.question }}</p>
      <p v-if="p.origin" class="mt-1.5 flex gap-1 border-l-2 pl-2 text-[11.5px] text-muted-foreground">
        <QuoteIcon class="mt-0.5 size-3 shrink-0" :aria-label="`${p.origin.round.label} 답변`" />
        <DeidText :text="p.origin.grounding" />
      </p>
      <p v-if="p.origin?.rationale" class="mt-1 line-clamp-2 text-[11px] text-muted-foreground/90">{{ p.origin.rationale }}</p>
      <div class="mt-2 flex items-center justify-between gap-2">
        <span class="truncate text-[11px] text-muted-foreground">{{ p.competency }}</span>
        <span v-if="askedSeq.get(p.id)" class="inline-flex items-center gap-1 text-[11.5px] font-medium text-success">
          <CheckIcon class="size-3.5" aria-hidden="true" />Q{{ askedSeq.get(p.id) }}
        </span>
        <Button v-else size="xs" variant="outline" :disabled="disabled || pendingId !== null" :aria-label="`이어 질문 기록: ${p.question}`" @click="emit('ask', p)">
          <CornerDownLeftIcon />
          {{ pendingId === p.id ? '기록 중…' : '질문하기' }}
        </Button>
      </div>
    </div>
  </section>

  <section aria-label="사전 질문" class="space-y-3">
    <div class="flex items-center justify-between">
      <h3 class="flex items-center gap-1.5 text-[13px] font-semibold">
        <ListChecksIcon class="size-4 text-muted-foreground" aria-hidden="true" />
        사전 질문
      </h3>
      <span class="text-xs text-muted-foreground tabular">{{ presets.filter((p) => askedSeq.has(p.id)).length }}/{{ presets.length }}</span>
    </div>
    <p v-if="presets.length === 0" class="text-[13px] text-muted-foreground">이 차수에는 사전 질문 세트가 없습니다. 직접 질문을 입력하세요.</p>
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
