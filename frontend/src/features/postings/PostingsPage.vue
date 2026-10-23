<script setup lang="ts">
import { ArrowUpRightIcon, BookCheckIcon, BriefcaseBusinessIcon, FilePenLineIcon } from '@lucide/vue'
import { RouterLink } from 'vue-router'

import { usePostings } from '@/api/queries'
import type { PostingStatus, PostingSummary } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import FadeIn from '@/components/common/FadeIn.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { POSTING_STATUS_LABEL } from '@/lib/labels'
import { formatFullDate } from '@/lib/time'

const q = usePostings()
const statusVariant: Record<PostingStatus, 'success' | 'outline' | 'secondary'> = { open: 'success', draft: 'outline', closed: 'secondary' }
const stats = (p: PostingSummary) =>
  [
    ['지원', p.counts.applications],
    ['통과', p.counts.passed],
    ['면접', p.counts.interviewing + p.counts.interviewed],
    ['평가 완료', p.counts.evaluated],
  ] as const
</script>

<template>
  <Page>
    <PageHeader
      eyebrow="FR-02"
      title="공고·역량 사전"
      description="공고마다 JD 원문과 역량 사전(1~5점 BARS)을 버전으로 관리합니다. 확정된 버전이 선별과 평가 기준이 됩니다."
    />
    <ErrorState v-if="q.isError" :error="q.error" @retry="q.refetch()" />
    <div v-else-if="!q.data" class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <Skeleton v-for="i in 3" :key="i" class="h-48 rounded-xl" />
    </div>
    <EmptyState v-else-if="q.data.length === 0" :icon="BriefcaseBusinessIcon" title="등록된 공고가 없습니다" />
    <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <FadeIn v-for="(p, i) in q.data" :key="p.id" :delay="i * 0.04">
        <RouterLink :to="`/postings/${p.id}`" class="group block h-full rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
          <Card class="flex h-full flex-col p-5 transition-colors group-hover:border-foreground/15">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-xs text-muted-foreground">{{ p.job_family }}</p>
                <h2 class="mt-1 text-[15px] leading-snug font-semibold">{{ p.title }}</h2>
              </div>
              <ArrowUpRightIcon
                class="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                aria-hidden="true"
              />
            </div>
            <div class="mt-3 flex items-center gap-2">
              <Badge :variant="statusVariant[p.status]">{{ POSTING_STATUS_LABEL[p.status] }}</Badge>
              <span class="text-xs text-muted-foreground">{{ formatFullDate(p.created_at) }} 등록</span>
            </div>
            <dl class="mt-5 grid grid-cols-4 gap-2 border-t pt-4">
              <div v-for="[label, v] in stats(p)" :key="label">
                <dt class="text-[11.5px] text-muted-foreground">{{ label }}</dt>
                <dd class="text-lg font-semibold tabular">{{ v }}</dd>
              </div>
            </dl>
            <div class="mt-auto pt-4 text-xs">
              <span v-if="!p.latest_competency_set" class="text-muted-foreground">역량 사전 없음</span>
              <span v-else class="flex flex-wrap items-center gap-1.5">
                <span v-if="p.approved_competency_set" class="inline-flex items-center gap-1 text-success">
                  <BookCheckIcon class="size-3.5" aria-hidden="true" />v{{ p.approved_competency_set.version }} 확정
                </span>
                <span v-else class="text-warning">확정본 없음</span>
                <span v-if="p.latest_competency_set.approved_at === null" class="inline-flex items-center gap-1 text-muted-foreground">
                  <FilePenLineIcon class="size-3.5" aria-hidden="true" />v{{ p.latest_competency_set.version }} 초안 검토 중
                </span>
              </span>
            </div>
          </Card>
        </RouterLink>
      </FadeIn>
    </div>
  </Page>
</template>
