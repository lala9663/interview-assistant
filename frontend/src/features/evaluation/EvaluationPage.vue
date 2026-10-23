<script setup lang="ts">
import { ArrowLeftIcon, BotIcon, ChartBarBigIcon, EyeOffIcon, LoaderIcon, MessageSquareTextIcon, TableIcon, UserRoundCheckIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { useEvaluation, useMe } from '@/api/queries'
import type { Score } from '@/api/types'
import AiReferenceNotice from '@/components/common/AiReferenceNotice.vue'
import AiScoringBadge from '@/components/common/AiScoringBadge.vue'
import DeidText from '@/components/common/DeidText.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import FadeIn from '@/components/common/FadeIn.vue'
import ModeBadge from '@/components/common/ModeBadge.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import SessionStatusBadge from '@/components/common/SessionStatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { QUESTION_SOURCE_LABEL, ROLE_LABEL } from '@/lib/labels'
import { formatDateTime, formatDuration, formatRelative } from '@/lib/time'

import AiEvidence from './AiEvidence.vue'
import InterviewerForm from './InterviewerForm.vue'
import ScoreChart from './ScoreChart.vue'
import ScoreTable from './ScoreTable.vue'
import { seriesColor } from './series'

const route = useRoute()
const sessionId = computed(() => String(route.params.sessionId ?? ''))
const q = useEvaluation(sessionId)
const me = useMe()
const view = ref<'chart' | 'table'>('chart')
const hideAi = ref(false)

const competencies = computed(() => q.data?.competency_set?.competencies ?? [])
const mine = computed(() => q.data?.interviewers.find((i) => i.interviewer.id === me.data?.id))
const aiDone = computed(() => q.data?.ai.status === 'completed')
const duration = computed(() => {
  const s = q.data?.session
  return s?.started_at && s.ended_at ? Math.round((new Date(s.ended_at).getTime() - new Date(s.started_at).getTime()) / 60000) : null
})
const answeredCount = computed(() => q.data?.qa_items.filter((x) => x.answer_deidentified).length ?? 0)
/** An interviewer's scores in rubric order (competencies they did not score are left out). */
const scoresInRubricOrder = (scores: readonly Score[]) =>
  competencies.value.flatMap((c) => scores.find((x) => x.competency === c.name) ?? [])
</script>

<template>
  <Page v-if="q.isError">
    <ErrorState :error="q.error" @retry="q.refetch()" />
  </Page>
  <Page v-else-if="!q.data">
    <Skeleton class="mb-2 h-3 w-24" />
    <Skeleton class="mb-6 h-7 w-72" />
    <Skeleton class="mb-4 h-16" />
    <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
      <Skeleton class="h-96" />
      <Skeleton class="h-96" />
    </div>
  </Page>
  <Page v-else-if="q.data.session.status !== 'completed'">
    <EmptyState :icon="ChartBarBigIcon" title="면접이 끝나면 평가가 열립니다" description="AI 채점은 면접 종료 후 시작되고, 면접관 점수도 종료 후에 입력합니다.">
      <template #action>
        <Button as-child variant="outline" size="sm">
          <RouterLink :to="`/sessions/${sessionId}/live`">면접 화면으로</RouterLink>
        </Button>
      </template>
    </EmptyState>
  </Page>
  <Page v-else>
    <PageHeader>
      <template #eyebrow>
        <RouterLink to="/sessions" class="inline-flex items-center gap-1 hover:text-foreground">
          <ArrowLeftIcon class="size-3.5" aria-hidden="true" />
          면접 · 평가 결과
        </RouterLink>
      </template>
      <template #title>
        <span class="flex flex-wrap items-center gap-3">
          <Pseudonym :value="q.data.candidate.pseudonym" size="lg" />
          <span class="text-base font-normal text-muted-foreground">{{ q.data.posting.title }}</span>
        </span>
      </template>
      <template #description>
        <span class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span v-if="q.data.session.started_at">{{ formatDateTime(q.data.session.started_at) }}</span>
          <span v-if="duration != null">{{ formatDuration(duration) }}</span>
          <ModeBadge :mode="q.data.session.mode" />
          <span>질문 {{ q.data.qa_items.length }}개</span>
        </span>
      </template>
      <template #actions>
        <SessionStatusBadge :status="q.data.session.status" />
        <AiScoringBadge :status="q.data.ai.status" />
      </template>
    </PageHeader>

    <AiReferenceNotice class="mb-4" />

    <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
      <div class="flex min-w-0 flex-col gap-4">
        <FadeIn>
          <Card>
            <CardHeader class="flex-wrap">
              <div>
                <CardTitle>역량별 점수</CardTitle>
                <CardDescription>AI 점수와 면접관 점수를 나란히 보여 주며 합산하지 않습니다</CardDescription>
              </div>
              <div class="flex items-center gap-3">
                <div class="flex items-center gap-2">
                  <Switch id="hide-ai" v-model="hideAi" />
                  <Label for="hide-ai" class="flex items-center gap-1 text-xs font-normal text-muted-foreground">
                    <EyeOffIcon class="size-3.5" aria-hidden="true" />
                    AI 점수 가리기
                  </Label>
                </div>
                <Segmented :model-value="view" aria-label="보기 방식" @update:model-value="(v) => (view = v as 'chart' | 'table')">
                  <SegmentedItem value="chart" aria-label="차트"><ChartBarBigIcon /></SegmentedItem>
                  <SegmentedItem value="table" aria-label="표"><TableIcon /></SegmentedItem>
                </Segmented>
              </div>
            </CardHeader>
            <CardContent>
              <p v-if="!aiDone && !hideAi && q.data.ai.status === 'running'" class="mb-3 flex items-center gap-1.5 text-xs text-brand">
                <LoaderIcon class="size-3.5 animate-spin" aria-hidden="true" />
                AI 채점이 끝나면 AI 막대가 추가됩니다
              </p>
              <EmptyState v-if="competencies.length === 0" compact :icon="ChartBarBigIcon" title="확정된 역량 사전이 없습니다" />
              <ScoreChart v-else-if="view === 'chart'" :ev="q.data" :hide-ai="hideAi || !aiDone" />
              <ScoreTable v-else :ev="q.data" :hide-ai="hideAi || !aiDone" />
            </CardContent>
          </Card>
        </FadeIn>

        <FadeIn :delay="0.05">
          <Card>
            <CardHeader>
              <div>
                <CardTitle class="flex items-center gap-1.5">
                  <BotIcon class="size-4 text-brand" aria-hidden="true" />
                  AI 점수 근거
                </CardTitle>
                <CardDescription>
                  {{ q.data.ai.model ? `${q.data.ai.model} · ${q.data.ai.prompt_version} · 답변마다 ${q.data.ai.samples}회 채점 후 집계` : 'AI 채점 전' }}
                </CardDescription>
              </div>
              <Badge variant="outline">참고용</Badge>
            </CardHeader>
            <CardContent>
              <EmptyState
                v-if="hideAi"
                compact
                :icon="EyeOffIcon"
                title="AI 점수를 가렸습니다"
                description="내 점수를 먼저 정하고 싶을 때 씁니다. 스위치를 끄면 다시 보입니다."
              />
              <div v-else-if="q.data.ai.status === 'running'" class="flex flex-col items-center gap-3 py-10 text-center">
                <span class="flex size-10 items-center justify-center rounded-xl border border-brand-border bg-brand-soft">
                  <LoaderIcon class="size-[18px] animate-spin text-brand" aria-hidden="true" />
                </span>
                <div>
                  <p class="text-sm font-medium">AI가 채점하는 중입니다</p>
                  <p class="mt-1 text-[13px] text-muted-foreground">
                    비식별 답변 {{ answeredCount }}개를 역량 루브릭으로 {{ q.data.ai.samples }}회씩 채점해 집계합니다. 근거 인용이 없는 점수는 저장하지 않습니다.
                  </p>
                </div>
              </div>
              <EmptyState
                v-else-if="q.data.ai.status === 'failed'"
                compact
                :icon="BotIcon"
                title="AI 채점에 실패했습니다"
                description="면접관 점수는 그대로 입력할 수 있습니다."
              />
              <AiEvidence v-else :ev="q.data" />
            </CardContent>
          </Card>
        </FadeIn>

        <FadeIn :delay="0.1">
          <Card>
            <CardHeader>
              <div>
                <CardTitle class="flex items-center gap-1.5">
                  <MessageSquareTextIcon class="size-4 text-muted-foreground" aria-hidden="true" />
                  Q&A 기록
                </CardTitle>
                <CardDescription>비식별 전사 기준</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <ol class="divide-y">
                <li v-for="qa in q.data.qa_items" :key="qa.id" class="py-3 first:pt-0 last:pb-0">
                  <div class="flex items-center gap-2">
                    <span class="font-mono text-[11px] font-semibold text-muted-foreground">Q{{ qa.seq }}</span>
                    <Badge :variant="qa.question_source === 'ai_suggested' ? 'brand' : 'outline'" class="py-0 text-[10.5px]">
                      {{ QUESTION_SOURCE_LABEL[qa.question_source] }}
                    </Badge>
                  </div>
                  <p class="mt-1 text-[13.5px] font-medium">{{ qa.question }}</p>
                  <p class="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                    <DeidText v-if="qa.answer_deidentified" :text="qa.answer_deidentified" />
                    <template v-else>답변 없음</template>
                  </p>
                </li>
              </ol>
            </CardContent>
          </Card>
        </FadeIn>
      </div>

      <div class="flex min-w-0 flex-col gap-4">
        <FadeIn :delay="0.05">
          <Card class="xl:sticky xl:top-[4.5rem]">
            <CardHeader>
              <div>
                <CardTitle class="flex items-center gap-1.5"><UserRoundCheckIcon class="size-4 text-muted-foreground" aria-hidden="true" />내 평가</CardTitle>
                <CardDescription>BARS 기준을 보고 역량마다 점수와 코멘트를 남기세요</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <InterviewerForm v-if="mine" :key="mine.submitted_at ?? 'new'" :session-id="sessionId" :competencies="competencies" :mine="mine" />
              <p v-else class="text-[13px] text-muted-foreground">이 면접의 면접관이 아니어서 점수를 입력할 수 없습니다.</p>
            </CardContent>
          </Card>
        </FadeIn>

        <FadeIn :delay="0.1">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>면접관별 점수</CardTitle>
                <CardDescription>면접관마다 따로 저장됩니다</CardDescription>
              </div>
            </CardHeader>
            <CardContent class="space-y-4">
              <div v-for="(iv, i) in q.data.interviewers" :key="iv.interviewer.id">
                <div class="flex items-center gap-2">
                  <span class="size-2.5 rounded-[3px]" :style="{ background: seriesColor(i + 1) }" aria-hidden="true"></span>
                  <span class="text-[13px] font-semibold">{{ iv.interviewer.name }}</span>
                  <span class="text-xs text-muted-foreground">{{ ROLE_LABEL[iv.role] }}</span>
                  <span class="ml-auto text-xs text-muted-foreground">
                    <template v-if="iv.submitted_at">{{ formatRelative(iv.submitted_at) }} 제출</template>
                    <Badge v-else variant="warning">제출 전</Badge>
                  </span>
                </div>
                <ul v-if="iv.scores.length > 0" class="mt-2 space-y-1.5 pl-[18px]">
                  <li v-for="sc in scoresInRubricOrder(iv.scores)" :key="sc.competency" class="text-[12.5px]">
                    <span class="text-muted-foreground">{{ sc.competency }}</span>
                    {{ ' ' }}<span class="font-semibold tabular">{{ sc.score }}</span>
                    <p v-if="sc.evidence" class="text-[12px] leading-snug text-muted-foreground/90">{{ sc.evidence }}</p>
                  </li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </FadeIn>
      </div>
    </div>
  </Page>
</template>
