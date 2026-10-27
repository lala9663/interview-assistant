<script setup lang="ts">
import { ArchiveIcon, ArchiveRestoreIcon, CheckIcon, PencilIcon, PlusIcon, RulerIcon, TriangleAlertIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { useRubricExamples, useRubricMutations } from '@/api/queries'
import type { RubricExample } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { toastError } from '@/lib/toast'

import { BANK_STATUS_LABEL, bankStatusVariant, competenciesOf } from './labels'
import RubricEditorDialog from './RubricEditorDialog.vue'

/** 평점 기준 예시: per competency, made-up answers for each score 1-5 that the scoring prompt shows as anchors. */
defineProps<{ isAdmin: boolean }>()

const family = ref('all')
const competency = ref('all')
const list = useRubricExamples(() => ({
  job_family: family.value === 'all' ? undefined : family.value,
  competency: competency.value === 'all' ? undefined : competency.value,
}))
const m = useRubricMutations()
const families = computed(() => list.data?.families ?? [])
const competencies = computed(() => (family.value === 'all' ? [] : competenciesOf(families.value, family.value)))

/** job family · competency -> examples, by score */
const groups = computed(() => {
  const out = new Map<string, RubricExample[]>()
  for (const r of list.data?.items ?? []) {
    const key = `${r.job_family} · ${r.competency}`
    ;(out.get(key) ?? out.set(key, []).get(key)!).push(r)
  }
  return [...out.entries()]
})

const editing = ref<RubricExample | null>(null)
const open = ref(false)
function edit(item: RubricExample | null) {
  editing.value = item
  open.value = true
}
const act = (fn: typeof m.approve, item: RubricExample, done: string) =>
  fn.mutate(item.id, { onSuccess: () => toast.success(done), onError: toastError('바꾸지 못했습니다') })
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <Select :model-value="family" @update:model-value="(v) => ((family = String(v)), (competency = 'all'))">
        <SelectTrigger class="h-8 w-36 text-[13px]" aria-label="직군 필터"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">모든 직군</SelectItem>
          <SelectItem v-for="f in families" :key="f.job_family" :value="f.job_family">{{ f.job_family }}</SelectItem>
        </SelectContent>
      </Select>
      <Select :model-value="competency" :disabled="family === 'all'" @update:model-value="(v) => (competency = String(v))">
        <SelectTrigger class="h-8 w-44 text-[13px]" aria-label="역량 필터"><SelectValue placeholder="모든 역량" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">모든 역량</SelectItem>
          <SelectItem v-for="c in competencies" :key="c" :value="c">{{ c }}</SelectItem>
        </SelectContent>
      </Select>
      <p class="text-xs text-muted-foreground">채점은 이 예시와의 유사도로 하지 않습니다. 행동 기준과 함께 수준을 가늠하는 기준점입니다.</p>
      <Button size="sm" class="ml-auto" @click="edit(null)">
        <PlusIcon />
        예시 추가
      </Button>
    </div>

    <ErrorState v-if="list.isError" :error="list.error" @retry="list.refetch()" />
    <Skeleton v-else-if="!list.data" class="h-48 rounded-xl" />
    <Card v-else-if="groups.length === 0">
      <EmptyState :icon="RulerIcon" title="평점 기준 예시가 없습니다" description="역량마다 1~5점 수준을 보여 주는 가상 답변을 추가하세요." />
    </Card>
    <Card v-for="[key, rows] in groups" v-else :key="key" class="overflow-hidden" data-testid="rubric-group">
      <h3 class="border-b px-4 py-2.5 text-[14px] font-semibold tracking-tight">{{ key }}</h3>
      <ul class="divide-y">
        <li v-for="r in rows" :key="r.id" class="flex gap-3 px-4 py-3" data-testid="rubric-item" :class="r.status === 'retired' && 'opacity-60'">
          <div class="flex w-12 shrink-0 flex-col items-center">
            <span class="text-[22px] leading-none font-semibold tabular">{{ r.score }}</span>
            <span class="text-[11px] text-muted-foreground">점</span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-1.5 text-xs">
              <Badge :variant="bankStatusVariant(r.status)">{{ BANK_STATUS_LABEL[r.status] }}</Badge>
              <span v-if="r.question" class="text-muted-foreground">질문: {{ r.question }}</span>
            </div>
            <p class="mt-1.5 text-[13px] leading-relaxed">{{ r.answer }}</p>
            <p v-if="r.rationale" class="mt-1 text-xs text-muted-foreground">이 점수인 이유: {{ r.rationale }}</p>
            <p v-for="o in r.overlaps" :key="o.id" class="mt-1.5 flex items-center gap-1.5 text-xs text-warning" data-testid="rubric-overlap">
              <TriangleAlertIcon class="size-3.5" aria-hidden="true" />
              {{ o.score }}점 예시와 거의 같습니다 (유사도 {{ o.similarity.toFixed(2) }}). 점수 사이가 흐려집니다.
            </p>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <Button v-if="r.status !== 'retired'" size="xs" variant="ghost" @click="edit(r)"><PencilIcon />고치기</Button>
              <template v-if="isAdmin">
                <Button v-if="r.status === 'draft'" size="xs" @click="act(m.approve, r, '승인했습니다')"><CheckIcon />승인</Button>
                <Button v-if="r.status !== 'retired'" size="xs" variant="ghost" class="text-muted-foreground" @click="act(m.retire, r, '폐기했습니다')">
                  <ArchiveIcon />폐기
                </Button>
                <Button v-else size="xs" variant="ghost" @click="act(m.restore, r, '초안으로 되살렸습니다')"><ArchiveRestoreIcon />되살리기</Button>
              </template>
            </div>
          </div>
        </li>
      </ul>
    </Card>

    <RubricEditorDialog
      :open="open"
      :item="editing"
      :families="families"
      :defaults="{ job_family: family === 'all' ? undefined : family, competency: competency === 'all' ? undefined : competency }"
      @close="open = false"
    />
  </div>
</template>
