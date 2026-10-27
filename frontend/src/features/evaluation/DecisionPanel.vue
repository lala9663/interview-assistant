<script setup lang="ts">
import { AwardIcon, CircleCheckIcon, CirclePauseIcon, CircleXIcon, GavelIcon, LockIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { useDecide } from '@/api/queries'
import { DECISION_STATUSES, type DecisionStatus, type Evaluation } from '@/api/types'
import AiReferenceNotice from '@/components/common/AiReferenceNotice.vue'
import DeidText from '@/components/common/DeidText.vue'
import StepStatusChip from '@/components/common/StepStatusChip.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { DECISION_LABEL, roundFullName } from '@/lib/labels'
import { formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'
import { cn } from '@/lib/utils'

/**
 * N차 결정: a person decides 합격 · 보류 · 불합격 with a reason, after every interviewer submitted.
 * AI scores are reference only. A change adds a revision; the history stays. In the last round a
 * pass makes a final candidate, whose official result is recorded on the recruiting site.
 */
const props = defineProps<{ ev: Evaluation }>()

const decide = useDecide(props.ev.session.id)
const panel = computed(() => props.ev.decision)
const choice = ref<DecisionStatus | null>(null)
const reason = ref('')
const LOOK: Record<DecisionStatus, { icon: typeof CircleCheckIcon; on: string }> = {
  passed: { icon: CircleCheckIcon, on: 'border-success bg-[color-mix(in_oklch,var(--success)_12%,transparent)] text-success' },
  hold: { icon: CirclePauseIcon, on: 'border-warning bg-[color-mix(in_oklch,var(--warning)_14%,transparent)] text-warning' },
  rejected: { icon: CircleXIcon, on: 'border-danger bg-[color-mix(in_oklch,var(--danger)_12%,transparent)] text-danger' },
}
const canSubmit = computed(() => panel.value.can_decide && choice.value !== null && reason.value.trim() !== '' && !decide.isPending)

function submit() {
  if (!choice.value) return
  const picked = choice.value
  decide.mutate(
    { decision: picked, reason: reason.value.trim() },
    {
      onSuccess: () => {
        const r = props.ev.round
        toast.success(`${props.ev.candidate.pseudonym} ${r.label} ${DECISION_LABEL[picked]}`, {
          description:
            picked === 'passed'
              ? panel.value.is_last_round
                ? '최종 합격 후보가 되었습니다. 공식 결과는 채용 사이트에 기록하세요.'
                : `${panel.value.next_round?.label ?? '다음 차수'} 면접을 잡을 수 있습니다.`
              : '결정과 사유는 감사 로그에 남습니다.',
        })
        choice.value = null
        reason.value = ''
      },
      onError: toastError('결정을 기록하지 못했습니다'),
    },
  )
}
</script>

<template>
  <Card data-testid="decision-panel">
    <CardHeader>
      <div>
        <CardTitle class="flex items-center gap-1.5">
          <GavelIcon class="size-4 text-muted-foreground" aria-hidden="true" />
          {{ ev.round.label }} 결정
        </CardTitle>
        <CardDescription>{{ roundFullName(ev.round) }} · 사람이 정하고 감사 로그에 남습니다</CardDescription>
      </div>
      <StepStatusChip v-if="panel.current" :status="panel.current.decision" />
    </CardHeader>
    <CardContent class="space-y-3">
      <AiReferenceNotice compact />
      <p
        v-if="panel.is_last_round"
        class="flex items-start gap-2 rounded-lg border bg-subtle px-3 py-2 text-[12.5px] leading-relaxed"
        data-testid="final-notice"
      >
        <AwardIcon class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span>합격하면 최종 합격 후보가 됩니다. 공식 결과는 채용 사이트에 기록합니다.</span>
      </p>
      <p v-else-if="panel.next_round" class="text-[12.5px] text-muted-foreground">
        합격하면 {{ roundFullName(panel.next_round) }} 대상이 됩니다. 불합격이면 다음 차수로 가지 않고, 보류는 결정 대기 목록에 남습니다.
      </p>

      <p v-if="!panel.can_decide" class="flex items-start gap-1.5 text-[12.5px] text-muted-foreground" data-testid="decision-blocked">
        <LockIcon class="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        {{ panel.blocked_reason }}
      </p>
      <form v-else class="space-y-3" @submit.prevent="submit">
        <div class="grid grid-cols-3 gap-2" role="radiogroup" :aria-label="`${ev.round.label} 결정`">
          <button
            v-for="d in DECISION_STATUSES"
            :key="d"
            type="button"
            role="radio"
            :aria-checked="choice === d"
            :class="
              cn(
                'flex items-center justify-center gap-1.5 rounded-lg border px-2 py-2 text-[13px] font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
                choice === d ? LOOK[d].on : 'bg-card text-foreground hover:bg-subtle',
              )
            "
            @click="choice = d"
          >
            <component :is="LOOK[d].icon" class="size-4" aria-hidden="true" />
            {{ DECISION_LABEL[d] }}
          </button>
        </div>
        <div class="space-y-1.5">
          <Label for="decision-reason">사유 <span class="text-danger">*</span></Label>
          <Textarea
            id="decision-reason"
            v-model="reason"
            rows="3"
            maxlength="1000"
            placeholder="면접관 평가를 근거로 적어 주세요. 이름·연락처는 저장할 때 가려집니다."
            class="text-[13px]"
          />
        </div>
        <Button type="submit" class="w-full" :disabled="!canSubmit">
          {{ decide.isPending ? '기록하는 중…' : panel.current ? '결정 바꾸기' : `${ev.round.label} 결정 기록` }}
        </Button>
      </form>

      <div v-if="panel.history.length > 0" class="border-t pt-3">
        <p class="mb-2 text-[11.5px] font-medium text-muted-foreground">결정 이력</p>
        <ol class="space-y-2" data-testid="decision-history">
          <li v-for="h in panel.history" :key="h.id" class="text-[12.5px] leading-snug">
            <div class="flex flex-wrap items-center gap-1.5">
              <StepStatusChip :status="h.decision" />
              <span class="text-[11.5px] text-muted-foreground">{{ h.decided_by_name }} · {{ formatDateTime(h.created_at) }}</span>
              <span class="ml-auto font-mono text-[10.5px] text-muted-foreground">#{{ h.revision }}</span>
            </div>
            <p class="mt-1 text-muted-foreground"><DeidText :text="h.reason" /></p>
          </li>
        </ol>
      </div>
    </CardContent>
  </Card>
</template>
