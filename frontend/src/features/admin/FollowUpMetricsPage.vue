<script setup lang="ts">
import { BookMarkedIcon, CopyXIcon, LockIcon, SparklesIcon, TimerIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import { useFollowUpMetrics, useMe } from '@/api/queries'
import type { SourceMetrics, SuggestionSource } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import StatTile from '@/features/dashboard/StatTile.vue'

import EmbeddingIndexPanel from './EmbeddingIndexPanel.vue'

/**
 * 관리자 > 꼬리질문 지표: how often interviewers use question-bank and AI suggestions, how soon the first card of
 * each source appears, and how many candidates were dropped as questions already asked.
 */
const me = useMe()
const isAdmin = computed(() => me.data?.is_admin === true)
const days = ref('30')
const metrics = useFollowUpMetrics(() => Number(days.value), isAdmin)

const SOURCE_LABEL: Record<SuggestionSource, string> = { bank: '질문 은행', ai: 'AI 생성' }
const by = (s: SuggestionSource) => metrics.data?.sources.find((x) => x.source === s) ?? null
const rate = (m: SourceMetrics | null) => (m?.adoption_rate == null ? '–' : `${Math.round(m.adoption_rate * 100)}%`)
const ms = (v: number | null | undefined) => (v == null ? '–' : v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}초`)
</script>

<template>
  <Page>
    <PageHeader eyebrow="관리자" title="꼬리질문 지표" description="출처별(질문 은행 / AI 생성) 채택률, 첫 후보까지 걸린 시간, 이미 한 질문이라 걸러낸 후보 수입니다.">
      <template v-if="isAdmin" #actions>
        <Segmented :model-value="days" aria-label="기간" @update:model-value="(v) => (days = v)">
          <SegmentedItem value="7">7일</SegmentedItem>
          <SegmentedItem value="30">30일</SegmentedItem>
          <SegmentedItem value="90">90일</SegmentedItem>
        </Segmented>
      </template>
    </PageHeader>

    <EmptyState v-if="me.data && !isAdmin" :icon="LockIcon" title="관리자만 볼 수 있습니다" description="꼬리질문 지표는 관리자 권한이 있는 계정에서만 봅니다." />
    <template v-else>
      <ErrorState v-if="metrics.isError" :error="metrics.error" @retry="metrics.refetch()" />
      <div v-else-if="!metrics.data" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Skeleton v-for="i in 4" :key="i" class="h-24 rounded-xl" />
      </div>
      <template v-else>
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="metrics-tiles">
          <StatTile label="질문 은행 채택률" :value="rate(by('bank'))" :hint="`보여 준 ${by('bank')?.shown ?? 0}개 중 ${by('bank')?.used ?? 0}개 사용`" :icon="BookMarkedIcon" :delay="0" />
          <StatTile label="AI 생성 채택률" :value="rate(by('ai'))" :hint="`보여 준 ${by('ai')?.shown ?? 0}개 중 ${by('ai')?.used ?? 0}개 사용`" :icon="SparklesIcon" :delay="0.04" />
          <StatTile
            label="첫 후보까지 (중앙값)"
            :value="ms(by('bank')?.first_ms_median)"
            :hint="`질문 은행 ${ms(by('bank')?.first_ms_median)} · AI ${ms(by('ai')?.first_ms_median)}`"
            :icon="TimerIcon"
            :delay="0.08"
          />
          <StatTile
            label="이미 한 질문이라 걸러냄"
            :value="metrics.data.duplicates.total"
            :hint="`질문 은행 ${metrics.data.duplicates.bank} · AI ${metrics.data.duplicates.ai}`"
            :icon="CopyXIcon"
            :delay="0.12"
          />
        </div>

        <Card class="mt-6 overflow-hidden">
          <div class="flex flex-wrap items-center gap-2 border-b px-4 py-3">
            <h2 class="text-[14px] font-semibold tracking-tight">출처별</h2>
            <Badge variant="outline" class="tabular">요청 {{ metrics.data.batches }}건</Badge>
            <span v-if="metrics.data.retrieval_model" class="ml-auto font-mono text-xs text-muted-foreground">검색 {{ metrics.data.retrieval_model }}</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full min-w-[640px] text-[13px]" data-testid="metrics-table">
              <thead>
                <tr class="border-b bg-subtle text-left text-xs text-muted-foreground">
                  <th class="py-2.5 pr-3 pl-4 font-medium">출처</th>
                  <th class="px-3 py-2.5 text-right font-medium">보여 준 후보</th>
                  <th class="px-3 py-2.5 text-right font-medium">채택 (수정 후)</th>
                  <th class="px-3 py-2.5 text-right font-medium">채택률</th>
                  <th class="px-3 py-2.5 text-right font-medium">첫 후보 중앙값</th>
                  <th class="px-3 py-2.5 text-right font-medium">첫 후보 p90</th>
                  <th class="py-2.5 pr-4 pl-3 text-right font-medium">걸러낸 중복</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in metrics.data.sources" :key="s.source" class="border-b last:border-0" :data-source="s.source">
                  <td class="py-2.5 pr-3 pl-4">
                    <Badge :variant="s.source === 'bank' ? 'brand' : 'outline'">
                      <BookMarkedIcon v-if="s.source === 'bank'" aria-hidden="true" />
                      <SparklesIcon v-else aria-hidden="true" />
                      {{ SOURCE_LABEL[s.source] }}
                    </Badge>
                  </td>
                  <td class="px-3 py-2.5 text-right tabular">{{ s.shown }}</td>
                  <td class="px-3 py-2.5 text-right tabular">{{ s.used }} <span class="text-muted-foreground">({{ s.edited }})</span></td>
                  <td class="px-3 py-2.5 text-right font-medium tabular">{{ rate(s) }}</td>
                  <td class="px-3 py-2.5 text-right tabular">{{ ms(s.first_ms_median) }}</td>
                  <td class="px-3 py-2.5 text-right tabular">{{ ms(s.first_ms_p90) }}</td>
                  <td class="py-2.5 pr-4 pl-3 text-right tabular">{{ metrics.data.duplicates[s.source] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="border-t px-4 py-2.5 text-xs text-muted-foreground">
            첫 후보까지는 꼬리질문 요청부터 그 출처의 첫 카드가 뜰 때까지입니다. AI 후보의 품질과 시간은 지금 쓰는 LLM에 따라 다르니, 실제 모델을 연결한 뒤 다시 보세요.
          </p>
        </Card>
        <EmbeddingIndexPanel class="mt-6" />
      </template>
    </template>
  </Page>
</template>
