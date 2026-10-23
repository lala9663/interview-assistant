<script setup lang="ts">
import { ArrowRightIcon, CalendarPlusIcon, MicIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { useMe, useSessions } from '@/api/queries'
import type { SessionStatus, SessionSummary } from '@/api/types'
import AiScoringBadge from '@/components/common/AiScoringBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import ModeBadge from '@/components/common/ModeBadge.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import PanelAvatars from '@/components/common/PanelAvatars.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import SessionStatusBadge from '@/components/common/SessionStatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/time'

type Filter = 'all' | Exclude<SessionStatus, 'cancelled'>
const FILTERS: { v: Filter; label: string }[] = [
  { v: 'all', label: '전체' },
  { v: 'in_progress', label: '진행 중' },
  { v: 'scheduled', label: '예정' },
  { v: 'completed', label: '완료' },
]
const ORDER: Record<SessionStatus, number> = { in_progress: 0, scheduled: 1, completed: 2, cancelled: 3 }

function sortSessions(list: readonly SessionSummary[]) {
  return [...list].sort((a, b) => {
    if (ORDER[a.status] !== ORDER[b.status]) return ORDER[a.status] - ORDER[b.status]
    const x = a.scheduled_at ?? ''
    const y = b.scheduled_at ?? ''
    return a.status === 'scheduled' ? x.localeCompare(y) : y.localeCompare(x)
  })
}

const q = useSessions()
const me = useMe()
const filter = ref<Filter>('all')
const counts = computed(() => {
  const c: Record<Filter, number> = { all: 0, in_progress: 0, scheduled: 0, completed: 0 }
  for (const s of q.data ?? []) {
    if (s.status === 'cancelled') continue
    c.all += 1
    c[s.status] += 1
  }
  return c
})
const rows = computed(() => sortSessions((q.data ?? []).filter((s) => s.status !== 'cancelled' && (filter.value === 'all' || s.status === filter.value))))
const myPending = (s: SessionSummary) => {
  const id = me.data?.id
  return Boolean(id) && s.status === 'completed' && s.interviewers.some((i) => i.interviewer_id === id) && !s.submitted_interviewer_ids.includes(id!)
}
</script>

<template>
  <Page>
    <PageHeader
      eyebrow="FR-04 ~ FR-08"
      title="면접"
      description="면접 세션을 열어 실시간 보조를 받고, 끝난 면접은 평가 화면에서 AI 참고 점수와 면접관 점수를 따로 확인합니다."
    >
      <template #actions>
        <Button as-child variant="outline" size="sm">
          <RouterLink to="/schedule">
            <CalendarPlusIcon />
            일정 잡기
          </RouterLink>
        </Button>
      </template>
    </PageHeader>
    <Card class="overflow-hidden">
      <div class="border-b px-4 py-3">
        <Segmented :model-value="filter" aria-label="상태 필터" @update:model-value="(v) => (filter = v as Filter)">
          <SegmentedItem v-for="f in FILTERS" :key="f.v" :value="f.v">
            {{ f.label }}
            <span class="text-[11.5px] text-muted-foreground tabular">{{ counts[f.v] }}</span>
          </SegmentedItem>
        </Segmented>
      </div>
      <ErrorState v-if="q.isError" :error="q.error" @retry="q.refetch()" />
      <div v-else-if="!q.data" class="space-y-2 p-4">
        <Skeleton v-for="i in 6" :key="i" class="h-12" />
      </div>
      <EmptyState v-else-if="rows.length === 0" :icon="MicIcon" title="해당하는 면접이 없습니다" />
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[860px] text-[13px]">
          <thead>
            <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
              <th class="py-2.5 pr-3 pl-4 font-medium">일시</th>
              <th class="px-3 py-2.5 font-medium">지원자</th>
              <th class="px-3 py-2.5 font-medium">공고</th>
              <th class="px-3 py-2.5 font-medium">방식</th>
              <th class="px-3 py-2.5 font-medium">면접관</th>
              <th class="px-3 py-2.5 font-medium">상태</th>
              <th class="px-3 py-2.5 font-medium">평가</th>
              <th class="py-2.5 pr-4 pl-3"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in rows" :key="s.id" class="border-b transition-colors last:border-0 hover:bg-subtle">
              <td class="py-3 pr-3 pl-4 tabular">{{ s.scheduled_at ? formatDateTime(s.scheduled_at) : '–' }}</td>
              <td class="px-3 py-3"><Pseudonym :value="s.candidate.pseudonym" size="sm" /></td>
              <td class="max-w-56 truncate px-3 py-3 text-muted-foreground">{{ s.posting.title }}</td>
              <td class="px-3 py-3"><ModeBadge :mode="s.mode" /></td>
              <td class="px-3 py-3"><PanelAvatars :panel="s.interviewers" /></td>
              <td class="px-3 py-3"><SessionStatusBadge :status="s.status" /></td>
              <td class="px-3 py-3">
                <div v-if="s.status === 'completed'" class="flex flex-wrap items-center gap-1.5">
                  <AiScoringBadge :status="s.ai_scoring" />
                  <Badge variant="outline" class="tabular">면접관 {{ s.submitted_interviewer_ids.length }}/{{ s.interviewers.length }}</Badge>
                  <Badge v-if="myPending(s)" variant="warning">내 평가 필요</Badge>
                </div>
                <span v-else class="text-muted-foreground">–</span>
              </td>
              <td class="py-3 pr-4 pl-3 text-right">
                <Button v-if="s.status === 'in_progress'" as-child size="xs">
                  <RouterLink :to="`/sessions/${s.id}/live`">
                    <MicIcon />
                    입장
                  </RouterLink>
                </Button>
                <Button v-else-if="s.status === 'scheduled'" as-child size="xs" variant="outline">
                  <RouterLink :to="`/sessions/${s.id}/live`">준비</RouterLink>
                </Button>
                <Button v-else-if="s.status === 'completed'" as-child size="xs" variant="outline">
                  <RouterLink :to="`/sessions/${s.id}/evaluation`">
                    평가
                    <ArrowRightIcon />
                  </RouterLink>
                </Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </Page>
</template>
