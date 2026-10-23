<script setup lang="ts">
import { InfoIcon } from '@lucide/vue'
import type { HTMLAttributes } from 'vue'

import { cn } from '@/lib/utils'

/** Mandatory notice wherever AI scores appear (FR-07, 개인정보보호법 제37조의2). */
const props = defineProps<{ compact?: boolean; class?: HTMLAttributes['class'] }>()
</script>

<template>
  <div
    role="note"
    :class="
      cn(
        'flex items-start gap-2.5 rounded-lg border border-[color-mix(in_oklch,var(--warning)_35%,transparent)] bg-[color-mix(in_oklch,var(--warning)_9%,transparent)] text-[13px] leading-relaxed',
        compact ? 'px-3 py-2' : 'px-4 py-3',
        props.class,
      )
    "
  >
    <InfoIcon class="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
    <div>
      <p class="font-semibold">AI 점수는 참고용이며 최종 판단은 면접관이 합니다.</p>
      <p v-if="!compact" class="text-muted-foreground">
        AI 점수와 면접관 점수는 따로 저장하고 합산하지 않습니다. AI 점수에는 답변 근거 인용과 신뢰도가 함께 붙습니다.
      </p>
    </div>
  </div>
</template>
