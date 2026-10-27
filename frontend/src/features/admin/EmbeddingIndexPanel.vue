<script setup lang="ts">
import { CircleAlertIcon, CircleCheckIcon, DatabaseIcon, RotateCwIcon } from '@lucide/vue'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'

import { useEmbeddingIndex, useRebuildIndex } from '@/api/queries'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

/**
 * The embedding index behind retrieval: which model's vectors searches use now, how many approved texts they
 * cover, and a new model's index while it is being built (searches keep the old one until it is ready).
 */
const status = useEmbeddingIndex()
const rebuild = useRebuildIndex()

const serving = computed(() => status.data?.indexes.find((i) => i.serving) ?? null)
const building = computed(() => status.data?.indexes.find((i) => i.status === 'building') ?? null)
const failed = computed(() => status.data?.indexes.find((i) => i.status === 'failed') ?? null)
const percent = (done: number, total: number) => (total ? Math.min(100, Math.round((done / total) * 100)) : 0)
const COUNT_LABEL: Record<string, string> = { question: '질문·꼬리질문 예시', rubric: '평점 기준 예시', competency_set: '확정 역량 사전' }

function start() {
  rebuild.mutate(undefined, {
    onSuccess: () => toast.success('색인을 다시 만듭니다', { description: '끝날 때까지 지금 색인으로 검색합니다.' }),
    onError: toastError('색인을 다시 만들지 못했습니다'),
  })
}
</script>

<template>
  <Card class="px-5 py-4" data-testid="embedding-index">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="flex items-center gap-1.5 text-[14px] font-semibold tracking-tight">
          <DatabaseIcon class="size-4 text-muted-foreground" aria-hidden="true" />
          임베딩 색인
        </h3>
        <p class="mt-0.5 text-xs text-muted-foreground">
          승인된 <RouterLink to="/question-bank" class="underline underline-offset-2">질문 은행</RouterLink>·평점 기준 예시·확정 역량 사전을 임베딩한 벡터입니다. 지원자 답변은
          색인하지 않습니다. 임베딩 모델을 바꾸면 새 색인을 만드는 동안 이전 색인으로 계속 검색합니다.
        </p>
      </div>
      <Button size="sm" variant="outline" :disabled="rebuild.isPending || Boolean(building)" @click="start">
        <RotateCwIcon />
        다시 만들기
      </Button>
    </div>

    <Skeleton v-if="!status.data" class="mt-3 h-12" />
    <template v-else>
      <div v-if="serving" class="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
        <Badge variant="success"><CircleCheckIcon aria-hidden="true" />검색 중</Badge>
        <span class="font-mono text-[12.5px]">{{ serving.model }}</span>
        <Badge variant="outline" class="tabular">{{ serving.dimensions }}차원</Badge>
        <span v-for="(n, kind) in status.data.counts" :key="kind" class="text-xs text-muted-foreground tabular">{{ COUNT_LABEL[kind] ?? kind }} {{ n }}</span>
        <span v-if="serving.finished_at" class="ml-auto text-xs text-muted-foreground">{{ formatDateTime(serving.finished_at) }} 완료</span>
      </div>
      <p v-else class="mt-3 text-[13px] text-muted-foreground">아직 검색할 색인이 없습니다. 질문 은행 후보는 색인이 준비되면 나옵니다.</p>

      <div v-if="building" class="mt-3 space-y-1.5" data-testid="index-building">
        <div class="flex items-center gap-2 text-[13px]">
          <Badge variant="live">새 색인 만드는 중</Badge>
          <span class="font-mono text-[12.5px]">{{ building.model }}</span>
          <span class="ml-auto text-xs text-muted-foreground tabular">{{ building.done }} / {{ building.total }}</span>
        </div>
        <div class="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" :aria-valuenow="percent(building.done, building.total)" aria-valuemin="0" aria-valuemax="100" aria-label="새 색인 진행률">
          <div class="h-full rounded-full bg-primary transition-[width]" :style="{ width: `${percent(building.done, building.total)}%` }"></div>
        </div>
        <p class="text-xs text-muted-foreground">끝날 때까지 꼬리질문과 검색은 {{ serving ? '이전 색인' : '색인 없이' }}으로 동작합니다.</p>
      </div>
      <p v-if="failed" class="mt-3 flex items-start gap-1.5 text-xs text-danger" role="alert">
        <CircleAlertIcon class="mt-px size-3.5 shrink-0" aria-hidden="true" />
        {{ failed.model }} 색인을 만들지 못했습니다: {{ failed.error }}
      </p>
    </template>
  </Card>
</template>
