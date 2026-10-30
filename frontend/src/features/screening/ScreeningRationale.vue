<script setup lang="ts">
import { BotIcon, CircleCheckIcon, CircleHelpIcon, CircleXIcon, MessageCircleQuestionIcon } from '@lucide/vue'
import { computed } from 'vue'

import type { RequirementCheck, Screening } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import { Badge, type BadgeVariants } from '@/components/ui/badge'
import { parseRationale, REQUIREMENT_KIND_LABEL, SCREENING_STATUS_LABEL, VERDICT_LABEL } from '@/lib/labels'

/**
 * 선별 근거. screening-v0.5 rows: one verdict per JD requirement (필수 first), the AI's
 * recommendation as a badge, points to check in the interview. Older rows keep their free text.
 */
const props = defineProps<{ screening: Screening }>()

const VERDICT_LOOK: Record<RequirementCheck['verdict'], { variant: NonNullable<BadgeVariants['variant']>; icon: typeof CircleCheckIcon }> = {
  met: { variant: 'success', icon: CircleCheckIcon },
  unmet: { variant: 'danger', icon: CircleXIcon },
  unclear: { variant: 'warning', icon: CircleHelpIcon },
}

const assessment = computed(() => props.screening.assessment)
const rows = computed(() => {
  const all = assessment.value?.requirements ?? []
  return [...all.filter((r) => r.kind === 'required'), ...all.filter((r) => r.kind === 'preferred')]
})
const legacy = computed(() => (assessment.value ? null : parseRationale(props.screening.rationale)))
</script>

<template>
  <div class="space-y-3" data-testid="screening-rationale">
    <div class="flex flex-wrap items-center gap-2">
      <Badge v-if="screening.recommendation" variant="brand" data-testid="ai-recommendation">
        <BotIcon aria-hidden="true" />
        AI 권고 · {{ SCREENING_STATUS_LABEL[screening.recommendation] }}
      </Badge>
      <span class="text-xs text-muted-foreground">적합도 {{ Math.round(screening.fit_score) }} · 참고용</span>
    </div>

    <template v-if="assessment">
      <p class="text-[13.5px] leading-relaxed"><DeidText :text="assessment.summary" /></p>
      <div v-if="rows.length > 0" class="overflow-hidden rounded-lg border">
        <table class="w-full text-[13px]" data-testid="requirement-table">
          <caption class="sr-only">JD 요건별 판단</caption>
          <thead>
            <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
              <th scope="col" class="w-[42%] px-3 py-2 font-medium">요건</th>
              <th scope="col" class="px-2 py-2 font-medium">판단</th>
              <th scope="col" class="px-3 py-2 font-medium">근거</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="i" class="border-b align-top last:border-0" data-testid="requirement-row">
              <td class="px-3 py-2.5">
                <span
                  :class="[
                    'mr-0.5 inline-block rounded px-1 py-px text-[10.5px] font-semibold',
                    r.kind === 'required' ? 'bg-foreground/10 text-foreground' : 'bg-muted text-muted-foreground',
                  ]"
                  >{{ REQUIREMENT_KIND_LABEL[r.kind] }}</span
                >{{ ' ' }}<DeidText :text="r.requirement" />
              </td>
              <td class="px-2 py-2.5">
                <Badge :variant="VERDICT_LOOK[r.verdict].variant">
                  <component :is="VERDICT_LOOK[r.verdict].icon" aria-hidden="true" />
                  {{ VERDICT_LABEL[r.verdict] }}
                </Badge>
              </td>
              <td class="px-3 py-2.5 text-muted-foreground">
                <DeidText :text="r.evidence" />
                <span v-if="r.source" class="mt-0.5 block text-[11.5px] text-muted-foreground/80">위치: <DeidText :text="r.source" /></span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="assessment.interview_checks.length > 0" class="rounded-lg border bg-subtle p-3">
        <p class="flex items-center gap-1.5 text-[12.5px] font-semibold">
          <MessageCircleQuestionIcon class="size-3.5 text-muted-foreground" aria-hidden="true" />
          면접에서 확인할 점
        </p>
        <ul class="mt-1.5 list-disc space-y-1 pl-5 text-[13px] text-muted-foreground marker:text-muted-foreground/50" data-testid="interview-checks">
          <li v-for="c in assessment.interview_checks" :key="c"><DeidText :text="c" /></li>
        </ul>
      </div>
    </template>

    <div v-else-if="legacy" class="rounded-lg border bg-subtle p-4" data-testid="legacy-rationale">
      <p class="text-[13.5px] leading-relaxed"><DeidText :text="legacy.summary" /></p>
      <ul v-if="legacy.strengths.length > 0" class="mt-3 space-y-1.5 text-[13px]">
        <li v-for="s in legacy.strengths" :key="s" class="flex gap-2">
          <span class="font-semibold text-success" aria-label="강점">+</span>
          <DeidText :text="s" />
        </li>
      </ul>
      <ul v-if="legacy.concerns.length > 0" class="mt-2 space-y-1.5 text-[13px] text-muted-foreground">
        <li v-for="s in legacy.concerns" :key="s" class="flex gap-2">
          <span class="font-semibold text-warning" aria-label="확인 필요">−</span>
          <DeidText :text="s" />
        </li>
      </ul>
    </div>
  </div>
</template>
