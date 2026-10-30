<script setup lang="ts">
import { CircleStopIcon, HourglassIcon } from '@lucide/vue'
import { computed } from 'vue'

import { Button } from '@/components/ui/button'
import { formatDateTime, formatDuration, MINUTE } from '@/lib/time'

/** Asks to end a session open far past its plan (most likely left running), see lib/session-clock.ts. */
const props = defineProps<{ elapsedMs: number; plannedMinutes: number; startedAt: string | null }>()
const emit = defineEmits<{ end: []; snooze: [] }>()

const open = computed(() => formatDuration(Math.floor(props.elapsedMs / MINUTE)))
</script>

<template>
  <div
    role="status"
    class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-[color-mix(in_oklch,var(--danger)_30%,transparent)] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)] px-4 py-2 text-[13px]"
    data-testid="long-open-banner"
  >
    <HourglassIcon class="size-4 shrink-0 text-danger" aria-hidden="true" />
    <p class="min-w-0 flex-1">
      <span class="font-semibold">{{ open }}째 열려 있는 면접입니다</span>
      <span class="text-muted-foreground"> ({{ startedAt ? `${formatDateTime(startedAt)} 시작, ` : '' }}예정 {{ plannedMinutes }}분)</span>.
      면접이 끝났다면 종료하세요. 종료해야 AI 참고 채점과 평가가 시작됩니다.
    </p>
    <div class="flex items-center gap-1.5">
      <Button size="xs" variant="ghost" @click="emit('snooze')">1시간 뒤 다시 알림</Button>
      <Button size="xs" variant="destructive" @click="emit('end')">
        <CircleStopIcon />
        면접 종료…
      </Button>
    </div>
  </div>
</template>
