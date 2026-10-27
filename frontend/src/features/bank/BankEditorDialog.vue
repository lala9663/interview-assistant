<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { endpoints } from '@/api/endpoints'
import { useBankMutations } from '@/api/queries'
import type { BankFamily, BankFlag, BankQuestionBody, QuestionBankItem } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toastError } from '@/lib/toast'

import FlagList from './FlagList.vue'
import { competenciesOf, lines, ROUND_CHOICES } from './labels'

/**
 * Write or edit a question-bank question. Prohibited-question warnings show while typing (rules on the
 * server, nothing stored); saving keeps them on the draft so the approver sees them too. Editing an approved
 * question sends it back to draft.
 */
const props = defineProps<{ open: boolean; item: QuestionBankItem | null; families: BankFamily[]; defaults?: Partial<BankQuestionBody> }>()
const emit = defineEmits<{ close: [] }>()

const m = useBankMutations()
const jobFamily = ref('')
const competency = ref('')
const round = ref('any')
const question = ref('')
const intent = ref('')
const followUps = ref('')
const flags = ref<BankFlag[]>([])

watch(
  () => props.open,
  (open) => {
    if (!open) return
    const src = props.item ?? props.defaults ?? {}
    jobFamily.value = src.job_family ?? props.families[0]?.job_family ?? ''
    competency.value = src.competency ?? ''
    round.value = src.round_position ? String(src.round_position) : 'any'
    question.value = src.question ?? ''
    intent.value = src.intent ?? ''
    followUps.value = (src.follow_ups ?? []).join('\n')
    flags.value = props.item?.flags ?? []
  },
  { immediate: true },
)

const competencies = computed(() => competenciesOf(props.families, jobFamily.value))

let timer: ReturnType<typeof setTimeout> | undefined
watch([question, followUps], () => {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    if (!question.value.trim()) {
      flags.value = []
      return
    }
    try {
      const r = await endpoints.checkQuestion({ question: question.value, follow_ups: lines(followUps.value) })
      flags.value = [...r.flags, ...(props.item?.question === question.value ? props.item.flags.filter((f) => f.source === 'ai') : [])]
    } catch {
      /* the check is advisory; saving checks again */
    }
  }, 350)
})

const body = (): BankQuestionBody => ({
  job_family: jobFamily.value,
  competency: competency.value,
  round_position: round.value === 'any' ? null : Number(round.value),
  question: question.value.trim(),
  intent: intent.value.trim(),
  follow_ups: lines(followUps.value),
})

const pending = computed(() => m.create.isPending || m.update.isPending)
const ready = computed(() => Boolean(jobFamily.value && competency.value && question.value.trim()))

function save() {
  if (!ready.value) return
  const done = (r: QuestionBankItem) => {
    toast.success(props.item?.status === 'approved' ? '고친 질문을 초안으로 돌렸습니다' : '초안으로 저장했습니다', {
      description: r.flags.length ? `금지 질문 경고 ${r.flags.length}개: 승인할 때 확인해야 합니다.` : '승인하면 꼬리질문 후보와 AI 예시로 쓰입니다.',
    })
    emit('close')
  }
  if (props.item) m.update.mutate({ id: props.item.id, body: body() }, { onSuccess: done, onError: toastError('저장하지 못했습니다') })
  else m.create.mutate(body(), { onSuccess: done, onError: toastError('저장하지 못했습니다') })
}
</script>

<template>
  <Dialog :open="open" @update:open="(o) => !o && emit('close')">
    <DialogContent class="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>{{ item ? '질문 고치기' : '질문 추가' }}</DialogTitle>
        <DialogDescription>
          직군·역량에 맞는 검수된 질문입니다. 승인한 질문만 실시간 면접의 꼬리질문 후보와 AI 예시로 쓰입니다.{{ item?.status === 'approved' ? ' 승인된 질문을 고치면 다시 승인해야 합니다.' : '' }}
        </DialogDescription>
      </DialogHeader>
      <form id="bank-form" class="space-y-4" @submit.prevent="save">
        <div class="grid gap-3 sm:grid-cols-3">
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
            <Label>차수</Label>
            <Select :model-value="round" @update:model-value="(v) => (round = String(v))">
              <SelectTrigger aria-label="차수"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="r in ROUND_CHOICES" :key="r.value" :value="r.value">{{ r.label }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label for="bank-question">질문</Label>
          <Textarea id="bank-question" v-model="question" class="min-h-20 text-[13.5px]" placeholder="행동 사례를 묻는 질문을 한 번에 하나씩 씁니다." />
          <FlagList :flags="flags" />
          <p v-if="flags.length" class="text-xs text-muted-foreground">직무와 무관한 개인 사정을 묻는 질문으로 보입니다. 저장은 되지만, 승인할 때 경고를 확인해야 합니다.</p>
        </div>
        <div class="space-y-1.5">
          <Label for="bank-intent">의도 <span class="font-normal text-muted-foreground">(선택)</span></Label>
          <Input id="bank-intent" v-model="intent" maxlength="200" placeholder="이 질문으로 확인하려는 것" />
        </div>
        <div class="space-y-1.5">
          <Label for="bank-followups">좋은 꼬리질문 예시 <span class="font-normal text-muted-foreground">(한 줄에 하나, 선택)</span></Label>
          <Textarea id="bank-followups" v-model="followUps" class="min-h-20 text-[13px]" />
          <p class="text-xs text-muted-foreground">답변이 이 예시와 가까우면 그대로 후보로 나오고, AI가 꼬리질문을 쓸 때 형식과 깊이의 예시로 봅니다.</p>
        </div>
      </form>
      <DialogFooter>
        <Button variant="outline" :disabled="pending" @click="emit('close')">취소</Button>
        <Button type="submit" form="bank-form" :disabled="!ready || pending">{{ pending ? '저장 중…' : '초안으로 저장' }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
