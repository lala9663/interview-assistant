<script setup lang="ts">
import DeidText from '@/components/common/DeidText.vue'
import { formatElapsed } from '@/lib/time'
import { cn } from '@/lib/utils'

import type { Turn } from './transcript-utils'

/** One speaker's stretch of the transcript, or a recorded question / typed answer standing in for one. */
defineProps<{
  speaker: Turn['speaker']
  parts: Turn['parts']
  /** since the session started; null when unknown */
  startMs: number | null
  /** why the text is not from the transcript: "기록한 질문", "수기 기록" */
  note?: string
}>()
</script>

<template>
  <div :class="cn('flex gap-3 rounded-lg px-3 py-2.5', speaker === 'interviewer' && 'bg-subtle')">
    <div class="w-[68px] shrink-0 pt-0.5">
      <div :class="cn('text-[12px] font-semibold', speaker === 'interviewer' ? 'text-brand' : 'text-foreground')">
        {{ speaker === 'interviewer' ? '면접관' : '지원자' }}
      </div>
      <div v-if="startMs !== null" class="text-[11px] text-muted-foreground tabular">{{ formatElapsed(startMs) }}</div>
      <div v-if="note" class="text-[11px] text-muted-foreground">{{ note }}</div>
    </div>
    <p :class="cn('min-w-0 flex-1 text-[14px] leading-[1.75]', speaker === 'interviewer' && 'font-medium')"
      ><span v-for="(p, i) in parts" :key="p.id" :class="cn('transition-colors duration-300', !p.final && 'text-muted-foreground/70')"
        >{{ i > 0 ? ' ' : '' }}<DeidText :text="p.text" /><span
          v-if="!p.final"
          class="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-caret bg-foreground/50"
          aria-hidden="true"
        ></span></span
    ></p>
  </div>
</template>
