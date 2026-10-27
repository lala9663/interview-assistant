<script setup lang="ts">
import { AwardIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { ProgressStep, StepStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { stepStatusLabel } from '@/lib/labels'

import { STEP_LOOK } from './status'

/**
 * Status chip of a step, apart from the round badge: 예정 gray, 진행 중 red dot (the REC tone),
 * 평가 대기, 결정 대기 (an action, the one blue), 합격 green, 보류 yellow, 불합격 red. The screening
 * step reads 통과 / 탈락, the final one 최종 합격 후보.
 */
const props = withDefaults(defineProps<{ status: StepStatus; kind?: ProgressStep['kind'] }>(), { kind: 'round' })
const look = computed(() => STEP_LOOK[props.status])
const text = computed(() => stepStatusLabel({ kind: props.kind, status: props.status }))
</script>

<template>
  <Badge v-if="status === 'in_progress'" variant="live" data-testid="status-chip">
    <span class="size-1.5 animate-live rounded-full bg-live" aria-hidden="true"></span>
    {{ text }}
  </Badge>
  <Badge v-else-if="kind === 'final'" variant="success" data-testid="status-chip">
    <AwardIcon aria-hidden="true" />
    {{ text }}
  </Badge>
  <Badge v-else :variant="look.variant" data-testid="status-chip">
    <component :is="look.icon" aria-hidden="true" />
    {{ text }}
  </Badge>
</template>
