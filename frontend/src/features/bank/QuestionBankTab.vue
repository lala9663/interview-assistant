<script setup lang="ts">
import { ArchiveIcon, ArchiveRestoreIcon, CheckIcon, FileUpIcon, LibraryBigIcon, PencilIcon, PlusIcon, SearchIcon, SparklesIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { useBankMutations, useQuestionBank } from '@/api/queries'
import type { BankStatus, QuestionBankFilter, QuestionBankItem } from '@/api/types'
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
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip } from '@/components/ui/tooltip'
import { formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

import BankEditorDialog from './BankEditorDialog.vue'
import FlagList from './FlagList.vue'
import ImportDialog from './ImportDialog.vue'
import { BANK_STATUS_LABEL, bankStatusVariant, competenciesOf, roundLabel } from './labels'

/** 질문 은행: list, filters, writing drafts (everyone), approving with the prohibited-question check, retiring and CSV (admins). */
defineProps<{ isAdmin: boolean }>()

const family = ref('all')
const competency = ref('all')
const round = ref('all')
const status = ref<'all' | BankStatus>('all')
const search = ref('')
const filter = computed<QuestionBankFilter>(() => ({
  job_family: family.value === 'all' ? undefined : family.value,
  competency: competency.value === 'all' ? undefined : competency.value,
  round: round.value === 'all' ? undefined : Number(round.value),
  status: status.value === 'all' ? undefined : status.value,
  q: search.value.trim() || undefined,
}))
const bank = useQuestionBank(filter)
const m = useBankMutations()
const families = computed(() => bank.data?.families ?? [])
const competencies = computed(() => (family.value === 'all' ? [] : competenciesOf(families.value, family.value)))

const editing = ref<QuestionBankItem | null>(null)
const editorOpen = ref(false)
const importOpen = ref(false)
const confirming = ref<QuestionBankItem | null>(null)
// The dialog's action closes it (clearing `confirming`) before its click handler runs: keep the target here.
let toConfirm: QuestionBankItem | null = null

function edit(item: QuestionBankItem | null) {
  editing.value = item
  editorOpen.value = true
}

function approve(item: QuestionBankItem, confirm = false) {
  if (item.flags.length && !confirm) {
    confirming.value = toConfirm = item
    return
  }
  m.approve.mutate(
    { id: item.id, confirm },
    {
      onSuccess: () => toast.success('승인했습니다', { description: '이제 실시간 면접의 꼬리질문 후보와 AI 예시로 쓰입니다.' }),
      onError: toastError('승인하지 못했습니다'),
    },
  )
}

const act = (fn: typeof m.retire, item: QuestionBankItem, done: string) =>
  fn.mutate(item.id, { onSuccess: () => toast.success(done), onError: toastError('바꾸지 못했습니다') })

function aiCheck(item: QuestionBankItem) {
  m.aiCheck.mutate(item.id, {
    onSuccess: (r) => {
      const found = r.flags.filter((f) => f.source === 'ai').length
      toast.success(found ? `AI가 경고 ${found}개를 찾았습니다` : 'AI 확인에서 문제를 찾지 못했습니다')
    },
    onError: toastError('AI 확인을 하지 못했습니다'),
  })
}
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
      <Select :model-value="round" @update:model-value="(v) => (round = String(v))">
        <SelectTrigger class="h-8 w-28 text-[13px]" aria-label="차수 필터"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">모든 차수</SelectItem>
          <SelectItem v-for="n in [1, 2, 3]" :key="n" :value="String(n)">{{ n }}차</SelectItem>
        </SelectContent>
      </Select>
      <Segmented :model-value="status" aria-label="상태" @update:model-value="(v) => (status = v as typeof status)">
        <SegmentedItem value="all">전체</SegmentedItem>
        <SegmentedItem v-for="s in ['approved', 'draft', 'retired'] as const" :key="s" :value="s">
          {{ BANK_STATUS_LABEL[s] }} <span class="ml-1 text-muted-foreground tabular">{{ bank.data?.counts[s] ?? '' }}</span>
        </SegmentedItem>
      </Segmented>
      <div class="relative">
        <SearchIcon class="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
        <Input v-model="search" class="h-8 w-52 pl-8 text-[13px]" placeholder="질문·의도 검색" aria-label="질문 검색" />
      </div>
      <div class="ml-auto flex gap-2">
        <Button v-if="isAdmin" size="sm" variant="outline" @click="importOpen = true">
          <FileUpIcon />
          CSV 가져오기
        </Button>
        <Button size="sm" @click="edit(null)">
          <PlusIcon />
          질문 추가
        </Button>
      </div>
    </div>

    <ErrorState v-if="bank.isError" :error="bank.error" @retry="bank.refetch()" />
    <div v-else-if="!bank.data" class="space-y-2">
      <Skeleton v-for="i in 5" :key="i" class="h-20 rounded-xl" />
    </div>
    <Card v-else-if="bank.data.items.length === 0">
      <EmptyState :icon="LibraryBigIcon" title="조건에 맞는 질문이 없습니다" description="필터를 바꾸거나 질문을 추가하세요." />
    </Card>
    <ul v-else class="space-y-2" data-testid="bank-list">
      <li v-for="item in bank.data.items" :key="item.id" data-testid="bank-item" :data-status="item.status">
        <Card :class="['px-4 py-3', item.status === 'retired' && 'opacity-60']">
          <div class="flex flex-wrap items-center gap-1.5 text-xs">
            <Badge :variant="bankStatusVariant(item.status)">{{ BANK_STATUS_LABEL[item.status] }}</Badge>
            <Badge variant="outline">{{ item.job_family }}</Badge>
            <Badge variant="outline">{{ item.competency }}</Badge>
            <Badge variant="outline">{{ roundLabel(item.round_position) }}</Badge>
            <Badge v-if="item.source === 'csv'" variant="outline">CSV</Badge>
            <span class="ml-auto text-muted-foreground">
              {{ item.created_by?.name ?? '' }}
              <template v-if="item.approved_by && item.approved_at"> · {{ item.approved_by.name }} 승인 {{ formatDateTime(item.approved_at) }}</template>
            </span>
          </div>
          <p class="mt-2 text-[14px] leading-relaxed font-medium">{{ item.question }}</p>
          <p v-if="item.intent" class="mt-0.5 text-xs text-muted-foreground">의도: {{ item.intent }}</p>
          <ul v-if="item.follow_ups.length" class="mt-1.5 space-y-0.5 border-l-2 border-border pl-2.5 text-[12.5px] text-muted-foreground">
            <li v-for="f in item.follow_ups" :key="f">↳ {{ f }}</li>
          </ul>
          <FlagList v-if="item.flags.length" :flags="item.flags" class="mt-2" />
          <div class="mt-2.5 flex flex-wrap gap-1.5">
            <Button v-if="item.status !== 'retired'" size="xs" variant="ghost" @click="edit(item)">
              <PencilIcon />
              고치기
            </Button>
            <template v-if="isAdmin">
              <Button v-if="item.status === 'draft'" size="xs" :disabled="m.approve.isPending" @click="approve(item)">
                <CheckIcon />
                승인
              </Button>
              <Tooltip v-if="item.status !== 'retired'" content="규칙이 못 잡는 금지 질문을 LLM이 한 번 더 봅니다 (질문만 보냅니다).">
                <Button size="xs" variant="ghost" :disabled="m.aiCheck.isPending" @click="aiCheck(item)">
                  <SparklesIcon />
                  AI 확인
                </Button>
              </Tooltip>
              <Button v-if="item.status !== 'retired'" size="xs" variant="ghost" class="text-muted-foreground" @click="act(m.retire, item, '폐기했습니다')">
                <ArchiveIcon />
                폐기
              </Button>
              <Button v-else size="xs" variant="ghost" @click="act(m.restore, item, '초안으로 되살렸습니다')">
                <ArchiveRestoreIcon />
                되살리기
              </Button>
            </template>
          </div>
        </Card>
      </li>
    </ul>

    <BankEditorDialog
      :open="editorOpen"
      :item="editing"
      :families="families"
      :defaults="{ job_family: family === 'all' ? undefined : family, competency: competency === 'all' ? undefined : competency }"
      @close="editorOpen = false"
    />
    <ImportDialog :open="importOpen" @close="importOpen = false" />

    <AlertDialog :open="confirming !== null" @update:open="(o) => !o && (confirming = null)">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>금지 질문 경고가 있는 질문입니다</AlertDialogTitle>
          <AlertDialogDescription>
            채용 면접에서 직무와 무관하게 물으면 안 되는 내용으로 보입니다. 직무와 관련 있는 질문인지 확인한 경우에만 승인하세요. 승인 기록에 확인한 경고가 남습니다.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <FlagList v-if="confirming" :flags="confirming.flags" />
        <AlertDialogFooter>
          <AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction data-testid="confirm-approve" @click="toConfirm && (approve(toConfirm, true), (toConfirm = null))">경고를 확인하고 승인</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
