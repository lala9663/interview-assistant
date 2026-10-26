<script setup lang="ts">
import { CircleAlertIcon, CircleCheckIcon, InfoIcon, PencilIcon, TimerIcon } from '@lucide/vue'

import type { ModelRoleState } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Tooltip } from '@/components/ui/tooltip'
import { formatDateTime, formatRelative } from '@/lib/time'

import DataLocationBadge from './DataLocationBadge.vue'

/** One AI role: what serves it now, whether it can run, where its data goes, and the last change. */
defineProps<{ state: ModelRoleState }>()
const emit = defineEmits<{ change: [] }>()
</script>

<template>
  <Card class="flex flex-col" data-testid="role-card" :data-role="state.role">
    <div class="flex items-start justify-between gap-3 px-5 pt-4">
      <div class="min-w-0">
        <h2 class="text-[15px] font-semibold tracking-tight">{{ state.label }}</h2>
        <p class="mt-0.5 text-xs text-muted-foreground">{{ state.description }}</p>
      </div>
      <Badge v-if="state.status === 'ready'" variant="success">
        <CircleCheckIcon aria-hidden="true" />
        사용 가능
      </Badge>
      <Badge v-else variant="danger">
        <CircleAlertIcon aria-hidden="true" />
        사용 불가
      </Badge>
    </div>

    <div class="flex-1 space-y-2.5 px-5 pt-3 pb-4">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-sm font-medium">{{ state.impl_label }}</span>
        <DataLocationBadge :location="state.data_location" />
      </div>
      <p class="font-mono text-[12.5px] text-muted-foreground" data-testid="role-model">{{ state.model }}</p>
      <p v-if="state.status_detail" class="flex items-start gap-1.5 text-xs text-danger">
        <CircleAlertIcon class="mt-px size-3.5 shrink-0" aria-hidden="true" />
        {{ state.status_detail }}
      </p>
      <p v-if="state.pinned_sessions > 0" class="flex items-start gap-1.5 text-xs text-muted-foreground">
        <TimerIcon class="mt-px size-3.5 shrink-0" aria-hidden="true" />
        진행 중인 면접 {{ state.pinned_sessions }}건은 시작할 때의 설정으로 끝까지 진행합니다.
      </p>
      <p v-if="state.note" class="flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
        <InfoIcon class="mt-px size-3.5 shrink-0" aria-hidden="true" />
        {{ state.note }}
      </p>
    </div>

    <div class="flex items-center justify-between gap-3 border-t px-5 py-3">
      <div class="min-w-0 text-xs text-muted-foreground">
        <template v-if="state.last_change">
          <Tooltip :content="formatDateTime(state.last_change.occurred_at)">
            <span class="tabular">{{ formatRelative(state.last_change.occurred_at) }}</span>
          </Tooltip>
          · {{ state.last_change.actor?.name ?? '시스템' }}
          <span v-if="state.last_change.reason" class="block truncate">{{ state.last_change.reason }}</span>
        </template>
        <template v-else>변경 기록 없음</template>
      </div>
      <Button size="sm" variant="outline" :aria-label="`${state.label} 변경`" @click="emit('change')">
        <PencilIcon />
        변경
      </Button>
    </div>
  </Card>
</template>
