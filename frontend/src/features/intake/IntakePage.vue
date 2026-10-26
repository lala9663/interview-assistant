<script setup lang="ts">
import { CircleAlertIcon, CircleCheckIcon, InboxIcon, LockIcon, RotateCwIcon, TimerIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'

import { useIntakeEvents, useIntakeRetry, useIntakeSummary, useMe } from '@/api/queries'
import type { IntakeEvent, IntakeStatus } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import PrivacyNote from '@/components/common/PrivacyNote.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import StatTile from '@/features/dashboard/StatTile.vue'
import { INTAKE_EVENT_LABEL, INTAKE_STATUS_LABEL, intakeCodeLabel } from '@/lib/labels'
import { formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

/**
 * 관리자 > 연동 현황: what the recruiting site sent (제출·수정·철회), how each event ended and why one
 * failed, counts per posting, processing times, and 다시 처리 for failed events. Names and applicant
 * numbers are never stored, so the screen only has pseudonyms.
 */
type StatusFilter = 'all' | 'pending' | IntakeStatus
const FILTERS: StatusFilter[] = ['all', 'pending', 'done', 'skipped', 'failed', 'rejected']
const FILTER_LABEL: Record<StatusFilter, string> = { ...INTAKE_STATUS_LABEL, all: '전체', pending: '대기·처리 중' }

const me = useMe()
const isAdmin = computed(() => me.data?.is_admin === true)
const summary = useIntakeSummary(isAdmin)
const status = ref<StatusFilter>('all')
const postingNo = ref('all')
const events = useIntakeEvents(
  () => ({
    status: status.value === 'all' || status.value === 'pending' ? undefined : status.value,
    posting_no: postingNo.value === 'all' ? undefined : postingNo.value,
  }),
  isAdmin,
)
const retry = useIntakeRetry()

const visible = computed(() => {
  const list = events.data ?? []
  return status.value === 'pending' ? list.filter((e) => e.status === 'queued' || e.status === 'processing') : list
})
const totals = computed(() => summary.data?.totals)
const pending = computed(() => (totals.value ? totals.value.queued + totals.value.processing : 0))
const seconds = (ms: number | null | undefined) => (ms == null ? '–' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}초`)

const statusVariant = (s: IntakeStatus) =>
  s === 'done' ? 'success' : s === 'failed' || s === 'rejected' ? 'danger' : s === 'skipped' ? 'outline' : 'live'

function retryOne(e: IntakeEvent) {
  retry.one.mutate(e.id, {
    onSuccess: () => toast.success(`${e.event_id}를 다시 처리합니다`),
    onError: toastError('다시 처리하지 못했습니다'),
  })
}

function retryCode(code: string) {
  retry.all.mutate(
    { failure_code: code },
    {
      onSuccess: (r) => toast.success(`${intakeCodeLabel(code)} ${r.requeued}건을 다시 처리합니다`),
      onError: toastError('다시 처리하지 못했습니다'),
    },
  )
}
</script>

<template>
  <Page>
    <PageHeader
      eyebrow="관리자"
      title="연동 현황"
      description="채용 사이트가 보낸 지원서 이벤트(제출·수정·철회)와 처리 결과입니다. 받으면 바로 응답하고 처리는 뒤에서 합니다. 공식 기록은 채용 사이트에 있습니다."
    >
      <template v-if="summary.data" #actions>
        <Badge :variant="summary.data.configured ? 'success' : 'warning'">
          {{ summary.data.configured ? '연동 키 설정됨' : '연동 키 없음 (IA_SITE_SECRET)' }}
        </Badge>
        <Badge variant="outline" class="tabular">처리 워커 {{ summary.data.workers }}</Badge>
      </template>
    </PageHeader>

    <EmptyState
      v-if="me.data && !isAdmin"
      :icon="LockIcon"
      title="관리자만 볼 수 있습니다"
      description="연동 현황은 관리자 권한이 있는 계정에서만 봅니다."
    />
    <template v-else>
      <ErrorState v-if="summary.isError" :error="summary.error" @retry="summary.refetch()" />
      <div v-else-if="!summary.data" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Skeleton v-for="i in 4" :key="i" class="h-24 rounded-xl" />
      </div>
      <template v-else>
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="받은 이벤트"
            :value="summary.data.totals.received"
            :hint="pending ? `대기 ${summary.data.totals.queued} · 처리 중 ${summary.data.totals.processing}` : '대기 중인 이벤트 없음'"
            :icon="InboxIcon"
            :live="pending > 0"
            :delay="0"
          />
          <StatTile label="반영" :value="summary.data.totals.done" :hint="`건너뜀 ${summary.data.totals.skipped} (이전 버전·철회)`" :icon="CircleCheckIcon" :delay="0.04" />
          <StatTile
            label="실패·거절"
            :value="summary.data.totals.failed + summary.data.totals.rejected"
            :hint="`실패 ${summary.data.totals.failed} · 거절 ${summary.data.totals.rejected}`"
            :icon="CircleAlertIcon"
            :delay="0.08"
          />
          <StatTile
            label="1건 처리 시간 (평균)"
            :value="seconds(summary.data.timing.avg_ms)"
            :hint="`p95 ${seconds(summary.data.timing.p95_ms)} · 분당 ${summary.data.timing.per_minute ?? '–'}건 · 대기 평균 ${seconds(summary.data.timing.avg_wait_ms)}`"
            :icon="TimerIcon"
            :delay="0.12"
          />
        </div>

        <div class="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
          <Card class="overflow-hidden">
            <h2 class="border-b px-4 py-3 text-[14px] font-semibold tracking-tight">공고별 수신</h2>
            <EmptyState v-if="summary.data.postings.length === 0" compact :icon="InboxIcon" title="아직 받은 지원서가 없습니다" />
            <div v-else class="overflow-x-auto">
              <table class="w-full min-w-[620px] text-[13px]">
                <thead>
                  <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
                    <th class="py-2.5 pr-3 pl-4 font-medium">공고</th>
                    <th class="px-3 py-2.5 text-right font-medium">수신</th>
                    <th class="px-3 py-2.5 font-medium">제출 · 수정 · 철회</th>
                    <th class="px-3 py-2.5 text-right font-medium">반영</th>
                    <th class="px-3 py-2.5 text-right font-medium">실패·거절</th>
                    <th class="py-2.5 pr-4 pl-3 text-right font-medium">지원서</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="p in summary.data.postings" :key="p.posting_no ?? '-'" class="border-b last:border-0" data-testid="intake-posting-row">
                    <td class="py-2.5 pr-3 pl-4">
                      <RouterLink v-if="p.posting" :to="`/postings/${p.posting.id}`" class="font-medium hover:underline">{{ p.posting.title }}</RouterLink>
                      <span v-else class="font-medium text-warning">연결된 공고 없음</span>
                      <span class="block font-mono text-[11.5px] text-muted-foreground">{{ p.posting_no ?? '번호 없음' }}</span>
                    </td>
                    <td class="px-3 py-2.5 text-right tabular">{{ p.received }}</td>
                    <td class="px-3 py-2.5 text-muted-foreground tabular">{{ p.submitted }} · {{ p.updated }} · {{ p.withdrawn }}</td>
                    <td class="px-3 py-2.5 text-right tabular">{{ p.done }}<span v-if="p.pending" class="ml-1 text-live">+{{ p.pending }}</span></td>
                    <td class="px-3 py-2.5 text-right tabular" :class="p.failed + p.rejected > 0 && 'text-danger'">{{ p.failed + p.rejected }}</td>
                    <td class="py-2.5 pr-4 pl-3 text-right font-medium tabular">{{ p.applications }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          <Card class="overflow-hidden">
            <h2 class="border-b px-4 py-3 text-[14px] font-semibold tracking-tight">실패 사유</h2>
            <EmptyState v-if="summary.data.failures.length === 0" compact :icon="CircleCheckIcon" title="실패한 이벤트가 없습니다" />
            <ul v-else class="divide-y">
              <li v-for="f in summary.data.failures" :key="f.code" class="flex items-center gap-3 px-4 py-2.5 text-[13px]" data-testid="intake-failure">
                <span class="min-w-0 flex-1">
                  <span class="block font-medium">{{ intakeCodeLabel(f.code) }}</span>
                  <span class="block font-mono text-[11px] text-muted-foreground">{{ f.code }}</span>
                </span>
                <span class="tabular">{{ f.count }}</span>
                <Button
                  v-if="f.retriable > 0"
                  size="xs"
                  variant="outline"
                  :disabled="retry.all.isPending"
                  :aria-label="`${intakeCodeLabel(f.code)} 모두 다시 처리`"
                  @click="retryCode(f.code)"
                >
                  <RotateCwIcon />
                  모두 다시 처리
                </Button>
              </li>
            </ul>
            <p class="border-t px-4 py-2.5 text-xs text-muted-foreground">
              모르는 공고 번호는 공고 화면에서 번호를 연결한 뒤, 마감은 공고를 연 뒤 다시 처리합니다. 거절(받지 않는 항목, 필수 칸 누락)은 저장하지 않았으므로 채용 사이트가 고쳐 다시 보내야 합니다.
            </p>
          </Card>
        </div>
      </template>

      <h2 class="mt-10 mb-3 text-[15px] font-semibold tracking-tight">받은 이벤트</h2>
      <Card class="overflow-hidden">
        <div class="flex flex-wrap items-center gap-3 border-b px-4 py-3">
          <Segmented :model-value="status" aria-label="처리 상태 필터" @update:model-value="(v) => (status = v as StatusFilter)">
            <SegmentedItem v-for="f in FILTERS" :key="f" :value="f">{{ FILTER_LABEL[f] }}</SegmentedItem>
          </Segmented>
          <Select :model-value="postingNo" @update:model-value="(v) => (postingNo = String(v))">
            <SelectTrigger class="ml-auto h-8 w-64 text-[13px]" aria-label="공고 번호 필터">
              <SelectValue placeholder="모든 공고" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">모든 공고</SelectItem>
              <SelectItem v-for="p in summary.data?.postings.filter((x) => x.posting_no) ?? []" :key="p.posting_no!" :value="p.posting_no!">
                {{ p.posting_no }} · {{ p.posting?.title ?? '연결 안 됨' }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <ErrorState v-if="events.isError" :error="events.error" @retry="events.refetch()" />
        <div v-else-if="!events.data" class="space-y-2 p-4">
          <Skeleton v-for="i in 6" :key="i" class="h-10" />
        </div>
        <EmptyState v-else-if="visible.length === 0" compact :icon="InboxIcon" title="조건에 맞는 이벤트가 없습니다" />
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[1080px] text-[13px]">
            <thead>
              <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
                <th class="py-2.5 pr-3 pl-4 font-medium">받은 시각</th>
                <th class="px-3 py-2.5 font-medium">종류</th>
                <th class="px-3 py-2.5 font-medium">공고</th>
                <th class="px-3 py-2.5 font-medium">지원자</th>
                <th class="px-3 py-2.5 font-medium">상태</th>
                <th class="px-3 py-2.5 font-medium">사유</th>
                <th class="px-3 py-2.5 text-right font-medium">처리</th>
                <th class="py-2.5 pr-4 pl-3"></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in visible" :key="e.id" class="border-b align-top last:border-0" data-testid="intake-event-row" :data-status="e.status">
                <td class="py-2.5 pr-3 pl-4 whitespace-nowrap tabular">
                  {{ formatDateTime(e.received_at) }}
                  <span class="block font-mono text-[11px] text-muted-foreground">{{ e.event_id }}</span>
                </td>
                <td class="px-3 py-2.5 whitespace-nowrap">
                  <span v-if="e.event_type">{{ INTAKE_EVENT_LABEL[e.event_type] }}</span>
                  <span v-else class="text-muted-foreground">–</span>
                  <span v-if="e.revision" class="ml-1 text-[11px] text-muted-foreground tabular">r{{ e.revision }}</span>
                </td>
                <td class="max-w-56 px-3 py-2.5">
                  <span class="block truncate">{{ e.posting?.title ?? '연결된 공고 없음' }}</span>
                  <span class="block font-mono text-[11px] text-muted-foreground">{{ e.posting_no ?? '–' }} · {{ e.application_no ?? '–' }}</span>
                </td>
                <td class="px-3 py-2.5">
                  <Pseudonym v-if="e.candidate" :value="e.candidate.pseudonym" size="sm" />
                  <span v-else class="text-muted-foreground">–</span>
                </td>
                <td class="px-3 py-2.5">
                  <Badge :variant="statusVariant(e.status)">{{ INTAKE_STATUS_LABEL[e.status] }}</Badge>
                  <span v-if="e.attempts > 1" class="ml-1 text-[11px] text-muted-foreground tabular">{{ e.attempts }}회</span>
                </td>
                <td class="max-w-96 px-3 py-2.5">
                  <template v-if="e.failure">
                    <span class="font-medium" data-testid="intake-reason">{{ intakeCodeLabel(e.failure.code) }}</span>
                    <span class="mt-0.5 line-clamp-2 block text-xs text-muted-foreground" :title="e.failure.message">{{ e.failure.message }}</span>
                  </template>
                  <span v-else-if="e.event_type === 'withdrawn' && e.result?.application_found === false" class="text-xs text-muted-foreground">
                    반영된 지원서가 없어 철회만 기록 (이전 이벤트는 건너뜀)
                  </span>
                  <span v-else-if="e.event_type === 'withdrawn' && Number(e.result?.cancelled_sessions) > 0" class="text-xs text-muted-foreground">
                    잡힌 면접 {{ e.result?.cancelled_sessions }}건 취소
                  </span>
                  <span v-else-if="e.result?.screening_reset" class="text-xs text-muted-foreground">수정 반영, 사람이 정한 선별을 보류로 되돌림</span>
                  <span v-else-if="e.dropped_fields.length > 0" class="text-xs text-muted-foreground">명세 밖 칸 {{ e.dropped_fields.length }}개 버림</span>
                  <span v-else class="text-muted-foreground">–</span>
                </td>
                <td class="px-3 py-2.5 text-right text-muted-foreground tabular">{{ seconds(e.processing_ms) }}</td>
                <td class="py-2.5 pr-4 pl-3 text-right">
                  <Button v-if="e.retriable" size="xs" variant="outline" :disabled="retry.one.isPending" :aria-label="`${e.event_id} 다시 처리`" @click="retryOne(e)">
                    <RotateCwIcon />
                    다시 처리
                  </Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
      <PrivacyNote class="mt-3">이름과 채용 사이트 지원자 번호는 저장하지 않습니다. 같은 사람인지는 번호의 키 해시로만 확인하고, 화면에는 가명만 보입니다.</PrivacyNote>
    </template>
  </Page>
</template>
