<script setup lang="ts">
import { CheckIcon, PenLineIcon } from '@lucide/vue'

import type { QAItem } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'

export type AnswerState = 'listening' | 'typing' | 'waiting' | 'answered'

/** The question on the table, large, above the transcript: readable at a glance while talking. */
defineProps<{ qa: QAItem; answer: AnswerState }>()
</script>

<template>
  <section aria-label="지금 질문" class="border-b px-5 py-2.5" data-testid="current-question">
    <div class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
      <span class="font-medium">지금 질문</span>
      <span class="font-mono font-semibold">Q{{ qa.seq }}</span>
      <Badge :variant="qa.question_source === 'ai_suggested' ? 'brand' : 'outline'" class="py-0 text-[10.5px]">
        {{ QUESTION_SOURCE_LABEL[qa.question_source] }}
      </Badge>
      <span v-if="answer === 'listening'" class="ml-auto flex items-center gap-1.5 font-medium text-live">
        <span class="size-1.5 animate-live rounded-full bg-live" aria-hidden="true"></span>
        답변 듣는 중
      </span>
      <span v-else-if="answer === 'typing'" class="ml-auto flex items-center gap-1 font-medium text-warning">
        <PenLineIcon class="size-3.5" aria-hidden="true" />
        답변을 아래에 기록하세요
      </span>
      <span v-else-if="answer === 'answered'" class="ml-auto flex items-center gap-1 font-medium text-success">
        <CheckIcon class="size-3.5" aria-hidden="true" />
        답변 끝
      </span>
      <span v-else class="ml-auto">답변 대기</span>
    </div>
    <p class="mt-1 line-clamp-2 text-[17px] leading-snug font-semibold" :title="qa.question">{{ qa.question }}</p>
  </section>
</template>
