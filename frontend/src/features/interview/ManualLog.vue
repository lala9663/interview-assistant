<script setup lang="ts">
import { PenLineIcon } from '@lucide/vue'
import { ref, watch } from 'vue'

import type { QAItem } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import { Badge } from '@/components/ui/badge'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** Manual mode: questions and typed answers (no recording / STT down). */
const props = defineProps<{ qaItems: QAItem[] }>()

const box = ref<HTMLDivElement>()
watch(
  () => props.qaItems.length,
  () => {
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  },
  { flush: 'post', immediate: true },
)
</script>

<template>
  <div ref="box" class="min-h-0 flex-1 overflow-y-auto px-5 py-4 scrollbar-thin">
    <div v-if="qaItems.length === 0" class="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-muted-foreground">
      <PenLineIcon class="size-5" aria-hidden="true" />
      <p>수기 모드입니다. 질문을 기록한 뒤 답변 요지를 직접 입력하세요.</p>
    </div>
    <ol class="space-y-3">
      <li v-for="q in qaItems" :key="q.id" class="rounded-lg border bg-card p-3.5">
        <div class="mb-1.5 flex items-center gap-2">
          <span class="font-mono text-[11px] font-semibold text-muted-foreground">Q{{ q.seq }}</span>
          <Badge :variant="q.question_source === 'ai_suggested' ? 'brand' : 'outline'" class="py-0 text-[10.5px]">
            {{ QUESTION_SOURCE_LABEL[q.question_source] }}
          </Badge>
        </div>
        <p class="text-[14px] font-medium">{{ q.question }}</p>
        <p :class="cn('mt-2 text-[13.5px] leading-relaxed', !q.answer_deidentified && 'text-muted-foreground italic')">
          <DeidText v-if="q.answer_deidentified" :text="q.answer_deidentified" />
          <template v-else>답변 미기록</template>
        </p>
      </li>
    </ol>
  </div>
</template>
