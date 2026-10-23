<script setup lang="ts">
import { CheckIcon, SendIcon } from '@lucide/vue'
import { computed, reactive } from 'vue'
import { toast } from 'vue-sonner'

import { useSubmitScores } from '@/api/queries'
import { BARS_LEVELS, type BarsLevel, type Competency, type InterviewerEvaluation } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip } from '@/components/ui/tooltip'
import { formatRelative } from '@/lib/time'
import { toastError } from '@/lib/toast'

/** The signed-in interviewer's own scores and comments (FR-08). Stored apart from AI scores. */
const props = defineProps<{ sessionId: string; competencies: readonly Competency[]; mine: InterviewerEvaluation }>()

const submit = useSubmitScores(props.sessionId)
const rows = reactive<Record<string, { score: number | null; comment: string }>>(
  Object.fromEntries(
    props.competencies.map((c) => {
      const s = props.mine.scores.find((x) => x.competency === c.name)
      return [c.name, { score: s?.score ?? null, comment: s?.evidence ?? '' }]
    }),
  ),
)
const missing = computed(() => props.competencies.filter((c) => rows[c.name]?.score == null).length)

// mutateAsync: a saved evaluation re-keys this form (fresh state), which would drop per-call mutate callbacks.
async function onSubmit() {
  const resubmit = Boolean(props.mine.submitted_at)
  try {
    await submit.mutateAsync({
      interviewerId: props.mine.interviewer.id,
      body: { scores: props.competencies.map((c) => ({ competency: c.name, score: rows[c.name]!.score!, comment: rows[c.name]!.comment })) },
    })
  } catch (e) {
    toastError('제출하지 못했습니다')(e)
    return
  }
  toast.success(resubmit ? '평가를 수정했습니다' : '평가를 제출했습니다', { description: 'AI 점수와 따로 저장되었습니다.' })
}
</script>

<template>
  <div class="space-y-4">
    <fieldset v-for="c in competencies" :key="c.name" class="space-y-2">
      <legend class="flex w-full items-baseline justify-between gap-2">
        <span class="text-[13px] font-semibold">{{ c.name }}</span>
        <span class="text-[11px] text-muted-foreground">1~5점</span>
      </legend>
      <Segmented
        :model-value="rows[c.name]!.score ? String(rows[c.name]!.score) : ''"
        class="grid w-full grid-cols-5"
        :aria-label="`${c.name} 점수`"
        @update:model-value="(v) => (rows[c.name]!.score = Number(v))"
      >
        <Tooltip v-for="l in BARS_LEVELS" :key="l" :content="c.bars[l]">
          <SegmentedItem
            :value="l"
            :aria-label="`${l}점: ${c.bars[l]}`"
            class="tabular aria-checked:bg-primary aria-checked:text-primary-foreground dark:aria-checked:bg-primary"
          >
            {{ l }}
          </SegmentedItem>
        </Tooltip>
      </Segmented>
      <p v-if="rows[c.name]!.score != null" class="rounded-md bg-subtle px-2.5 py-1.5 text-[12px] leading-snug text-muted-foreground">
        <span class="font-medium text-foreground">{{ rows[c.name]!.score }}점 기준</span> · {{ c.bars[String(rows[c.name]!.score) as BarsLevel] }}
      </p>
      <Textarea
        v-model="rows[c.name]!.comment"
        placeholder="근거가 된 답변과 관찰을 적어 주세요"
        :aria-label="`${c.name} 코멘트`"
        class="min-h-14 text-[13px]"
      />
    </fieldset>
    <div class="flex items-center justify-between gap-3 border-t pt-4">
      <span class="text-xs text-muted-foreground">
        <span v-if="mine.submitted_at" class="inline-flex items-center gap-1 text-success">
          <CheckIcon class="size-3.5" aria-hidden="true" />
          {{ formatRelative(mine.submitted_at) }} 제출
        </span>
        <template v-else>{{ missing > 0 ? `${missing}개 역량 점수가 남았습니다` : '모든 역량에 점수를 매겼습니다' }}</template>
      </span>
      <Button :disabled="missing > 0 || submit.isPending" @click="onSubmit">
        <SendIcon />
        {{ submit.isPending ? '저장 중…' : mine.submitted_at ? '수정 제출' : '평가 제출' }}
      </Button>
    </div>
  </div>
</template>
