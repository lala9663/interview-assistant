<script setup lang="ts">
import {
  ArrowRightIcon,
  BriefcaseBusinessIcon,
  CalendarClockIcon,
  CalendarOffIcon,
  ClipboardListIcon,
  HistoryIcon,
  InboxIcon,
  MicIcon,
} from '@lucide/vue'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { useActivity, useDashboard, useMe } from '@/api/queries'
import AiScoringBadge from '@/components/common/AiScoringBadge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import FadeIn from '@/components/common/FadeIn.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate, formatRelative } from '@/lib/time'

import ActivityFeed from './ActivityFeed.vue'
import PipelineRow from './PipelineRow.vue'
import SessionLine from './SessionLine.vue'
import StatTile from './StatTile.vue'

const me = useMe()
const dash = useDashboard()
const activity = useActivity(14)
const today = new Date()

const live = computed(() => dash.data?.today_sessions.find((s) => s.status === 'in_progress'))
const upcoming = computed(() => dash.data?.today_sessions.filter((s) => s.status === 'scheduled').length ?? 0)
const openPostings = computed(() => dash.data?.pipeline.filter((p) => p.posting.status === 'open').length ?? 0)
const applications = computed(() => dash.data?.pipeline.reduce((sum, p) => sum + p.counts.applications, 0) ?? 0)
</script>

<template>
  <Page v-if="dash.isError">
    <ErrorState :error="dash.error" @retry="dash.refetch()" />
  </Page>
  <Page v-else>
    <PageHeader
      :eyebrow="formatDate(today)"
      :title="me.data ? `안녕하세요, ${me.data.name}님` : '대시보드'"
      description="공고별 진행 현황과 오늘 면접, 최근 활동을 한눈에 봅니다."
    >
      <template v-if="live" #actions>
        <Button as-child>
          <RouterLink :to="`/sessions/${live.id}/live`">
            <MicIcon />
            진행 중 면접으로
          </RouterLink>
        </Button>
      </template>
    </PageHeader>

    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <template v-if="dash.data">
        <StatTile :delay="0" label="진행 중 공고" :value="openPostings" :hint="`지원서 ${applications}건`" :icon="BriefcaseBusinessIcon" to="/postings" />
        <StatTile
          :delay="0.04"
          label="오늘 면접"
          :value="dash.data.today_sessions.length"
          :hint="live ? `1건 진행 중 · ${upcoming}건 예정` : `${upcoming}건 예정`"
          :icon="CalendarClockIcon"
          to="/sessions"
          :live="Boolean(live)"
        />
        <StatTile
          :delay="0.08"
          label="내 평가 대기"
          :value="dash.data.pending_my_scores.length"
          :hint="dash.data.pending_my_scores.length > 0 ? '점수를 입력해야 평가가 마무리됩니다' : '모두 제출했습니다'"
          :icon="ClipboardListIcon"
          :to="dash.data.pending_my_scores[0] ? `/sessions/${dash.data.pending_my_scores[0].id}/evaluation` : undefined"
        />
        <StatTile :delay="0.12" label="서류 보류" :value="dash.data.hold_count" hint="사람의 검토가 필요한 지원서" :icon="InboxIcon" to="/screening" />
      </template>
      <template v-else>
        <Skeleton v-for="i in 4" :key="i" class="h-[108px] rounded-xl" />
      </template>
    </div>

    <div class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
      <div class="flex min-w-0 flex-col gap-4">
        <FadeIn :delay="0.1">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>공고별 진행 현황</CardTitle>
                <CardDescription>서류 → 면접 → 평가 단계별 인원</CardDescription>
              </div>
              <Button as-child variant="ghost" size="sm">
                <RouterLink to="/screening">
                  서류 선별
                  <ArrowRightIcon />
                </RouterLink>
              </Button>
            </CardHeader>
            <CardContent class="divide-y">
              <template v-if="dash.data">
                <PipelineRow v-for="row in dash.data.pipeline" :key="row.posting.id" :row="row" />
              </template>
              <div v-else class="space-y-4 py-2">
                <Skeleton v-for="i in 3" :key="i" class="h-14" />
              </div>
            </CardContent>
          </Card>
        </FadeIn>

        <FadeIn :delay="0.16">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>최근 활동</CardTitle>
                <CardDescription>감사 로그에서 사람이 볼 만한 항목만 보여 줍니다</CardDescription>
              </div>
              <HistoryIcon class="size-4 text-muted-foreground" aria-hidden="true" />
            </CardHeader>
            <CardContent>
              <ErrorState v-if="activity.isError" :error="activity.error" class="py-6" @retry="activity.refetch()" />
              <template v-else-if="activity.data">
                <ActivityFeed v-if="activity.data.length > 0" :items="activity.data" />
                <EmptyState v-else compact :icon="HistoryIcon" title="아직 활동이 없습니다" />
              </template>
              <div v-else class="space-y-3">
                <div v-for="i in 5" :key="i" class="flex gap-3">
                  <Skeleton class="size-7 rounded-full" />
                  <div class="flex-1 space-y-1.5 pt-1">
                    <Skeleton class="h-3.5 w-4/5" />
                    <Skeleton class="h-3 w-16" />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </FadeIn>
      </div>

      <div class="flex min-w-0 flex-col gap-4">
        <FadeIn :delay="0.12">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>오늘 면접</CardTitle>
                <CardDescription>{{ formatDate(today) }}</CardDescription>
              </div>
              <Button as-child variant="ghost" size="sm">
                <RouterLink to="/sessions">
                  전체
                  <ArrowRightIcon />
                </RouterLink>
              </Button>
            </CardHeader>
            <CardContent class="px-3">
              <template v-if="dash.data">
                <ul v-if="dash.data.today_sessions.length > 0" class="space-y-1">
                  <SessionLine v-for="s in dash.data.today_sessions" :key="s.id" :s="s" />
                </ul>
                <EmptyState v-else compact :icon="CalendarOffIcon" title="오늘 잡힌 면접이 없습니다">
                  <template #action>
                    <Button as-child size="sm" variant="outline">
                      <RouterLink to="/schedule">일정 잡기</RouterLink>
                    </Button>
                  </template>
                </EmptyState>
              </template>
              <div v-else class="space-y-2 px-2">
                <Skeleton v-for="i in 3" :key="i" class="h-14" />
              </div>
            </CardContent>
          </Card>
        </FadeIn>

        <FadeIn :delay="0.18">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>내 평가 대기</CardTitle>
                <CardDescription>면접관 점수는 AI 점수와 따로 저장됩니다</CardDescription>
              </div>
            </CardHeader>
            <CardContent class="px-3">
              <template v-if="dash.data">
                <ul v-if="dash.data.pending_my_scores.length > 0" class="space-y-1">
                  <li v-for="s in dash.data.pending_my_scores" :key="s.id">
                    <RouterLink :to="`/sessions/${s.id}/evaluation`" class="flex items-center gap-3 rounded-lg px-2.5 py-2.5 transition-colors hover:bg-subtle">
                      <div class="min-w-0 flex-1">
                        <Pseudonym :value="s.candidate.pseudonym" size="sm" />
                        <div class="mt-0.5 truncate text-xs text-muted-foreground">
                          {{ s.posting.title }} · {{ s.ended_at ? formatRelative(s.ended_at) : '' }} 종료
                        </div>
                      </div>
                      <AiScoringBadge :status="s.ai_scoring" />
                      <Badge variant="warning">입력 필요</Badge>
                    </RouterLink>
                  </li>
                </ul>
                <EmptyState v-else compact :icon="ClipboardListIcon" title="제출할 평가가 없습니다" />
              </template>
              <Skeleton v-else class="mx-2 h-14" />
            </CardContent>
          </Card>
        </FadeIn>
      </div>
    </div>
  </Page>
</template>
