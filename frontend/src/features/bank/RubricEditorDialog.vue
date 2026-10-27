<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { useRubricMutations } from '@/api/queries'
import type { BankFamily, RubricExample, RubricExampleBody } from '@/api/types'
import PrivacyNote from '@/components/common/PrivacyNote.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toastError } from '@/lib/toast'

import { competenciesOf } from './labels'

/** Write or edit a rubric anchor: a made-up answer showing one score (1-5) of one competency. */
const props = defineProps<{ open: boolean; item: RubricExample | null; families: BankFamily[]; defaults?: Partial<RubricExampleBody> }>()
const emit = defineEmits<{ close: [] }>()

const m = useRubricMutations()
const jobFamily = ref('')
const competency = ref('')
const score = ref('3')
const question = ref('')
const answer = ref('')
const rationale = ref('')

watch(
  () => props.open,
  (open) => {
    if (!open) return
    const src = props.item ?? props.defaults ?? {}
    jobFamily.value = src.job_family ?? props.families[0]?.job_family ?? ''
    competency.value = src.competency ?? ''
    score.value = String(src.score ?? 3)
    question.value = src.question ?? ''
    answer.value = src.answer ?? ''
    rationale.value = src.rationale ?? ''
  },
  { immediate: true },
)

const competencies = computed(() => competenciesOf(props.families, jobFamily.value))
const pending = computed(() => m.create.isPending || m.update.isPending)
const ready = computed(() => Boolean(jobFamily.value && competency.value && answer.value.trim()))

function save() {
  if (!ready.value) return
  const body: RubricExampleBody = {
    job_family: jobFamily.value,
    competency: competency.value,
    score: Number(score.value),
    question: question.value.trim(),
    answer: answer.value.trim(),
    rationale: rationale.value.trim(),
  }
  const done = (r: RubricExample) => {
    const near = r.overlaps.map((o) => `${o.score}점 예시 (${o.similarity.toFixed(2)})`).join(', ')
    if (near) toast.warning('다른 점수의 예시와 거의 같습니다', { description: `${near}. 점수 사이가 흐려지지 않게 고쳐 주세요.` })
    else toast.success('초안으로 저장했습니다')
    emit('close')
  }
  if (props.item) m.update.mutate({ id: props.item.id, body }, { onSuccess: done, onError: toastError('저장하지 못했습니다') })
  else m.create.mutate(body, { onSuccess: done, onError: toastError('저장하지 못했습니다') })
}
</script>

<template>
  <Dialog :open="open" @update:open="(o) => !o && emit('close')">
    <DialogContent class="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{{ item ? '평점 기준 예시 고치기' : '평점 기준 예시 추가' }}</DialogTitle>
        <DialogDescription>
          역량의 한 점수가 어떤 수준인지 보여 주는 가상 답변입니다. 승인하면 AI 채점 프롬프트에 행동 기준과 함께 기준점으로 들어갑니다.
        </DialogDescription>
      </DialogHeader>
      <form id="rubric-form" class="space-y-4" @submit.prevent="save">
        <div class="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <div class="space-y-1.5">
            <Label>직군</Label>
            <Select :model-value="jobFamily" @update:model-value="(v) => ((jobFamily = String(v)), (competency = ''))">
              <SelectTrigger aria-label="직군"><SelectValue placeholder="직군" /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="f in families" :key="f.job_family" :value="f.job_family">{{ f.job_family }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label>역량</Label>
            <Select :model-value="competency" @update:model-value="(v) => (competency = String(v))">
              <SelectTrigger aria-label="역량"><SelectValue placeholder="역량" /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="c in competencies" :key="c" :value="c">{{ c }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <Label>점수</Label>
            <Segmented :model-value="score" aria-label="점수" @update:model-value="(v) => (score = v)">
              <SegmentedItem v-for="n in ['1', '2', '3', '4', '5']" :key="n" :value="n">{{ n }}점</SegmentedItem>
            </Segmented>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label for="rubric-question">질문 <span class="font-normal text-muted-foreground">(선택)</span></Label>
          <Input id="rubric-question" v-model="question" placeholder="이 답변이 대답하는 질문" />
        </div>
        <div class="space-y-1.5">
          <Label for="rubric-answer">예시 답변</Label>
          <Textarea id="rubric-answer" v-model="answer" class="min-h-28 text-[13px]" />
        </div>
        <div class="space-y-1.5">
          <Label for="rubric-why">이 점수인 이유 <span class="font-normal text-muted-foreground">(선택)</span></Label>
          <Input id="rubric-why" v-model="rationale" placeholder="행동 기준(BARS)의 어느 수준과 맞는지" />
        </div>
        <PrivacyNote>
          사람이 새로 쓴 가상 답변만 넣습니다. 지원자의 실제 답변과 거의 같으면 저장되지 않습니다. AI 채점은 지원자 답변이 이 예시와 얼마나 비슷한지로
          점수를 매기지 않고, 행동 기준과 함께 수준을 가늠하는 기준점으로만 씁니다.
        </PrivacyNote>
      </form>
      <DialogFooter>
        <Button variant="outline" :disabled="pending" @click="emit('close')">취소</Button>
        <Button type="submit" form="rubric-form" :disabled="!ready || pending">{{ pending ? '저장 중…' : '초안으로 저장' }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
