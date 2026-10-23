<script setup lang="ts">
import { MessageSquareTextIcon } from '@lucide/vue'
import { ref, watch } from 'vue'

import type { QAItem } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { Badge } from '@/components/ui/badge'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'
import { formatTime } from '@/lib/time'
import { cn } from '@/lib/utils'

const props = defineProps<{ qaItems: QAItem[]; editedIds: ReadonlySet<string>; answeringId: string | null }>()

const end = ref<HTMLLIElement>()
watch(
  () => props.qaItems.length,
  () => end.value?.scrollIntoView({ block: 'nearest' }),
  { flush: 'post' },
)
</script>

<template>
  <EmptyState
    v-if="qaItems.length === 0"
    compact
    :icon="MessageSquareTextIcon"
    title="기록된 질문이 없습니다"
    description="사전 질문, AI 제안, 직접 입력 모두 여기에 순서대로 쌓입니다."
  />
  <TransitionGroup
    v-else
    tag="ol"
    class="space-y-2"
    aria-label="Q&A 기록"
    enter-active-class="transition-[opacity,transform] duration-250"
    enter-from-class="opacity-0 translate-x-3"
  >
    <li v-for="q in qaItems" :key="q.id" class="rounded-lg border bg-card p-3">
      <div class="mb-1 flex items-center gap-1.5">
        <span class="font-mono text-[11px] font-semibold text-muted-foreground">Q{{ q.seq }}</span>
        <Badge :variant="q.question_source === 'ai_suggested' ? 'brand' : 'outline'" class="py-0 text-[10.5px]">
          {{ QUESTION_SOURCE_LABEL[q.question_source] }}
        </Badge>
        <Badge v-if="editedIds.has(q.id)" variant="outline" class="py-0 text-[10.5px]">수정함</Badge>
        <span v-if="q.asked_at" class="ml-auto text-[11px] text-muted-foreground tabular">{{ formatTime(q.asked_at) }}</span>
      </div>
      <p class="text-[13px] leading-snug font-medium">{{ q.question }}</p>
      <p v-if="q.answer_deidentified" class="mt-1.5 line-clamp-3 text-[12.5px] leading-relaxed text-muted-foreground">
        <DeidText :text="q.answer_deidentified" />
      </p>
      <p v-else :class="cn('mt-1.5 text-[12px] text-muted-foreground', answeringId === q.id && 'text-live')">
        {{ answeringId === q.id ? '● 답변 중' : '답변 대기' }}
      </p>
    </li>
    <li key="end" ref="end" aria-hidden="true"></li>
  </TransitionGroup>
</template>
