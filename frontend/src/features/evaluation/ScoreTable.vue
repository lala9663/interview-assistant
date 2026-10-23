<script setup lang="ts">
import { computed } from 'vue'

import type { Evaluation } from '@/api/types'
import { buildCompetencyRows, confidenceLabel, LOW_CONFIDENCE } from '@/lib/scoring'
import { cn, formatScore } from '@/lib/utils'

/** Table view of the same numbers. Deliberately no total/average column (FR-07). */
const props = defineProps<{ ev: Evaluation; hideAi: boolean }>()
const rows = computed(() => buildCompetencyRows(props.ev))
</script>

<template>
  <div class="overflow-x-auto">
    <table class="w-full text-[13px]" aria-label="역량별 점수 표">
      <thead>
        <tr class="border-b text-left text-xs text-muted-foreground">
          <th class="py-2 pr-3 font-medium">역량</th>
          <template v-if="!hideAi">
            <th class="px-3 py-2 text-right font-medium">AI (참고)</th>
            <th class="px-3 py-2 font-medium">신뢰도</th>
          </template>
          <th v-for="iv in ev.interviewers" :key="iv.interviewer.id" class="px-3 py-2 text-right font-medium">{{ iv.interviewer.name }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.competency" class="border-b last:border-0" :data-testid="`score-row-${r.competency}`">
          <td class="py-2.5 pr-3 font-medium">{{ r.competency }}</td>
          <template v-if="!hideAi">
            <td class="px-3 py-2.5 text-right font-semibold tabular" data-testid="ai-score">
              <span v-if="r.ai == null" class="font-normal text-muted-foreground">근거 없음</span>
              <template v-else>{{ formatScore(r.ai) }}</template>
            </td>
            <td class="px-3 py-2.5 text-xs">
              <template v-if="r.aiConfidence == null">–</template>
              <span v-else :class="cn('tabular', r.aiConfidence < LOW_CONFIDENCE ? 'font-medium text-warning' : 'text-muted-foreground')">
                {{ confidenceLabel(r.aiConfidence) }} · {{ r.aiConfidence.toFixed(2) }}
              </span>
            </td>
          </template>
          <td v-for="iv in ev.interviewers" :key="iv.interviewer.id" class="px-3 py-2.5 text-right font-semibold tabular" data-testid="interviewer-score">
            <span v-if="r.interviewers[iv.interviewer.id] == null" class="font-normal text-muted-foreground">미제출</span>
            <template v-else>{{ r.interviewers[iv.interviewer.id] }}</template>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="mt-2 text-[11.5px] text-muted-foreground">합계·평균 열은 두지 않습니다. AI 점수와 면접관 점수는 따로 저장하고 합산하지 않습니다.</p>
  </div>
</template>
