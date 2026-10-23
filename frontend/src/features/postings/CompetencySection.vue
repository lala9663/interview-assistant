<script setup lang="ts">
import { BookCheckIcon, CopyPlusIcon, LockIcon, PencilIcon, SparklesIcon } from '@lucide/vue'
import { computed, ref, toRaw } from 'vue'
import { toast } from 'vue-sonner'

import {
  useApproveCompetencySet,
  useCompetencySets,
  useCreateCompetencySet,
  useGenerateCompetencySet,
  useInterviewers,
  useUpdateCompetencySet,
} from '@/api/queries'
import type { Competency } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime, formatFullDate } from '@/lib/time'
import { toastError } from '@/lib/toast'

import CompetencyEditor from './CompetencyEditor.vue'
import CompetencyRubric from './CompetencyRubric.vue'
import { isComplete } from './competency-utils'

const props = defineProps<{ postingId: string }>()

const sets = useCompetencySets(() => props.postingId)
const interviewers = useInterviewers()
const picked = ref<number | null>(null)
const draft = ref<Competency[] | null>(null)
const create = useCreateCompetencySet(() => props.postingId)
const update = useUpdateCompetencySet(() => props.postingId)
const approve = useApproveCompetencySet(() => props.postingId)
const generate = useGenerateCompetencySet(() => props.postingId)

const list = computed(() => sets.data ?? [])
const current = computed(() => list.value.find((s) => s.version === picked.value) ?? list.value[list.value.length - 1])
const newNames = computed(() => {
  const approvedLatest = [...list.value].reverse().find((s) => s.approved_at)
  const c = current.value
  if (!c || !approvedLatest || c.id === approvedLatest.id) return undefined
  return new Set(c.competencies.map((x) => x.name).filter((n) => !approvedLatest.competencies.some((a) => a.name === n)))
})
const approverName = (id: string | null) => interviewers.data?.find((i) => i.id === id)?.name ?? id ?? ''
const canSave = computed(() => draft.value !== null && draft.value.length > 0 && draft.value.every(isComplete))
/** Query data is read-only reactive state: edit a plain deep copy. */
const cloneCompetencies = (c: readonly Competency[]): Competency[] => structuredClone(toRaw(c) as Competency[])

const onGenerate = () =>
  generate.mutate(undefined, {
    onSuccess: (s) => {
      picked.value = s.version
      toast.success(`AI가 v${s.version} 초안을 만들었습니다`, { description: '검토하고 수정한 뒤 확정하세요.' })
    },
    onError: toastError('초안을 만들지 못했습니다'),
  })

const onNewDraft = () => {
  const c = current.value
  if (!c) return
  create.mutate(cloneCompetencies(c.competencies), {
    onSuccess: (s) => {
      picked.value = s.version
      draft.value = structuredClone(s.competencies)
    },
    onError: toastError('새 버전을 만들지 못했습니다'),
  })
}

const onEdit = () => {
  if (current.value) draft.value = cloneCompetencies(current.value.competencies)
}

const onSave = () => {
  const c = current.value
  if (!c || !draft.value) return
  update.mutate(
    { id: c.id, competencies: draft.value },
    {
      onSuccess: () => {
        draft.value = null
        toast.success(`v${c.version} 초안을 저장했습니다`)
      },
      onError: toastError('저장하지 못했습니다'),
    },
  )
}

const onApprove = () => {
  const c = current.value
  if (!c) return
  approve.mutate(c.id, {
    onSuccess: () => toast.success(`v${c.version}을 확정했습니다`, { description: '이후 선별과 평가는 이 버전을 기준으로 합니다.' }),
    onError: toastError('확정하지 못했습니다'),
  })
}

const onPick = (v: string) => {
  if (draft.value === null) picked.value = Number(v)
}
</script>

<template>
  <ErrorState v-if="sets.isError" :error="sets.error" @retry="sets.refetch()" />
  <Skeleton v-else-if="!sets.data" class="h-96" />
  <div v-else class="space-y-4">
    <div class="flex flex-wrap items-center gap-3">
      <Segmented v-if="list.length > 0" :model-value="current ? String(current.version) : ''" aria-label="버전 선택" @update:model-value="onPick">
        <SegmentedItem v-for="s in list" :key="s.id" :value="String(s.version)" :disabled="draft !== null">
          v{{ s.version }}
          <LockIcon v-if="s.approved_at" class="size-3" aria-label="확정" />
          <span v-else class="text-[11px] text-muted-foreground">초안</span>
        </SegmentedItem>
      </Segmented>
      <div class="ml-auto flex flex-wrap gap-2">
        <template v-if="draft !== null">
          <Button variant="ghost" size="sm" @click="draft = null">취소</Button>
          <Button size="sm" :disabled="update.isPending || !canSave" @click="onSave">
            {{ update.isPending ? '저장 중…' : '초안 저장' }}
          </Button>
        </template>
        <template v-else>
          <Button variant="brand" size="sm" :disabled="generate.isPending" @click="onGenerate">
            <SparklesIcon :class="generate.isPending ? 'animate-pulse' : undefined" />
            {{ generate.isPending ? 'JD로 초안 만드는 중…' : 'AI 초안 생성' }}
          </Button>
          <Button v-if="current?.approved_at" variant="outline" size="sm" :disabled="create.isPending" @click="onNewDraft">
            <CopyPlusIcon />이 버전으로 새 초안
          </Button>
          <template v-else-if="current">
            <Button variant="outline" size="sm" @click="onEdit">
              <PencilIcon />
              편집
            </Button>
            <AlertDialog>
              <AlertDialogTrigger as-child>
                <Button size="sm" :disabled="approve.isPending">
                  <BookCheckIcon />
                  확정
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>v{{ current.version }}을 확정할까요?</AlertDialogTitle>
                  <AlertDialogDescription>
                    확정한 버전은 수정할 수 없고, 이후 서류 선별과 면접 평가(AI·면접관 모두)의 기준이 됩니다. 이미 진행된 평가는 당시 버전을 유지합니다.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>취소</AlertDialogCancel>
                  <AlertDialogAction @click="onApprove">확정</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </template>
        </template>
      </div>
    </div>

    <div v-if="current" class="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
      <Badge v-if="current.approved_at" variant="success">
        <LockIcon />
        확정
      </Badge>
      <Badge v-else variant="warning">초안</Badge>
      <span>
        v{{ current.version }} · 역량 {{ current.competencies.length }}개 · {{ formatFullDate(current.created_at) }} 생성
        <template v-if="current.approved_at"> · {{ approverName(current.approved_by) }} 확정 ({{ formatDateTime(current.approved_at) }})</template>
      </span>
      <span v-if="!current.approved_at">· 확정 전까지 수정할 수 있습니다</span>
    </div>

    <Card v-if="list.length === 0">
      <EmptyState
        :icon="SparklesIcon"
        title="역량 사전이 없습니다"
        description="JD를 바탕으로 AI가 역량 목록과 1~5점 행동 기준 초안을 만들고, 담당자가 검토해 확정합니다."
      >
        <template #action>
          <Button variant="brand" size="sm" :disabled="generate.isPending" @click="onGenerate">
            <SparklesIcon />
            AI 초안 생성
          </Button>
        </template>
      </EmptyState>
    </Card>
    <CompetencyEditor v-else-if="draft !== null" v-model="draft" />
    <CompetencyRubric v-else-if="current" :competencies="current.competencies" :new-names="newNames" />
  </div>
</template>
