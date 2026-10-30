<script setup lang="ts">
import { PenLineIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { SessionDetail, StreamStatus } from '@/api/types'
import { Tooltip } from '@/components/ui/tooltip'
import { clockPhase, DEFAULT_PLANNED_MINUTES, elapsedMs, formatClock } from '@/lib/session-clock'
import { formatTime, MINUTE } from '@/lib/time'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

import type { Connection } from './use-transcript'

const props = defineProps<{ detail: SessionDetail; status: StreamStatus | null; connection: Connection }>()

const now = useNow(1000)
const planned = DEFAULT_PLANNED_MINUTES
const ms = computed(() => elapsedMs(props.detail.session.started_at, now.value))
const phase = computed(() => clockPhase(ms.value, planned))
const clock = computed(() => formatClock(ms.value, planned))
const progress = computed(() => Math.min(100, (ms.value / (planned * MINUTE)) * 100))
const clockHint = computed(() => {
  const started = props.detail.session.started_at
  return `예정 ${planned}분 (차수에 길이가 없어 면접 잡기와 같은 1시간)${started ? ` · ${formatTime(started)} 시작` : ''}`
})
const manual = computed(() => !props.detail.session.has_recording)
const stt = computed<{ label: string; cls: string; hint: string; detail?: string | null }>(() => {
  const { connection, status } = props
  if (connection === 'error' || status?.stt === 'down')
    return { label: '전사 끊김', cls: 'bg-danger', hint: '녹음은 계속됩니다. 답변은 수기로 기록할 수 있습니다.' }
  if (connection === 'reconnecting' || connection === 'connecting')
    return { label: '전사 연결 중', cls: 'bg-warning animate-pulse', hint: '스트리밍 STT에 연결하는 중입니다.' }
  if (status?.stt === 'degraded') return { label: '전사 지연', cls: 'bg-warning', hint: '전사가 평소보다 늦습니다.' }
  return {
    label: '전사 정상',
    detail: status?.latency_ms ? `${(status.latency_ms / 1000).toFixed(1)}초` : null,
    cls: 'bg-success',
    hint: '부분 전사 지연 목표 0.5초 이하',
  }
})
</script>

<template>
  <div class="flex items-center gap-3 text-[12.5px] whitespace-nowrap">
    <span
      v-if="manual"
      class="flex items-center gap-1.5 rounded-md bg-[color-mix(in_oklch,var(--warning)_12%,transparent)] px-2 py-1 font-medium text-warning"
    >
      <PenLineIcon class="size-3.5" aria-hidden="true" />
      수기 모드 · 녹음 안 함
    </span>
    <span v-else class="flex items-center gap-1.5 rounded-md bg-[color-mix(in_oklch,var(--live)_12%,transparent)] px-2 py-1 font-semibold text-live">
      <span class="size-2 shrink-0 animate-live rounded-full bg-live" aria-hidden="true"></span>
      REC
    </span>
    <Tooltip :content="clockHint">
      <span tabindex="0" class="flex flex-col gap-1 outline-none" data-testid="session-clock" :data-phase="phase">
        <span
          :class="
            cn(
              'font-semibold tabular',
              phase === 'over' && 'text-warning',
              phase === 'long_open' && 'text-danger',
            )
          "
          :aria-label="`경과 시간 ${clock}`"
          >{{ clock }}</span
        >
        <span class="h-1 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <span
            :class="cn('block h-full rounded-full transition-[width] duration-1000', phase === 'on_time' ? 'bg-foreground/45' : phase === 'over' ? 'bg-warning' : 'bg-danger')"
            :style="{ width: `${progress}%` }"
          ></span>
        </span>
      </span>
    </Tooltip>
    <Tooltip v-if="!manual" :content="stt.hint">
      <span tabindex="0" class="flex items-center gap-1.5 text-muted-foreground outline-none">
        <span :class="cn('size-2 shrink-0 rounded-full', stt.cls)" aria-hidden="true"></span>
        <span class="tabular">
          {{ stt.label }}<span v-if="stt.detail" class="hidden xl:inline"> · {{ stt.detail }}</span>
        </span>
      </span>
    </Tooltip>
  </div>
</template>
