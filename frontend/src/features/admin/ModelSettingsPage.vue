<script setup lang="ts">
import { LockIcon, TriangleAlertIcon } from '@lucide/vue'
import { computed, ref } from 'vue'

import { useMe, useModelCatalog, useModelHistory, useModelSettings } from '@/api/queries'
import type { ModelGroup, ModelRoleState } from '@/api/types'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

import ChangeModelDialog from './ChangeModelDialog.vue'
import EmbeddingIndexPanel from './EmbeddingIndexPanel.vue'
import ModelHistory from './ModelHistory.vue'
import RoleCard from './RoleCard.vue'

/** 관리자 > 모델 설정: the AI provider of each role, its tests, changes without a restart, and history. */
const me = useMe()
const isAdmin = computed(() => me.data?.is_admin === true)
const settings = useModelSettings(isAdmin)
const catalog = useModelCatalog(isAdmin)
const history = useModelHistory(isAdmin)

const GROUPS: { key: ModelGroup; title: string; description: string }[] = [
  { key: 'ai', title: 'AI 모델', description: 'LLM, STT, 임베딩, 화자분리. 진행 중인 면접은 시작할 때의 모델을 끝까지 씁니다.' },
  {
    key: 'documents',
    title: '서류 읽기',
    description:
      '지원 서류를 텍스트 층으로 읽을지 OCR로 읽을지, 어떤 도구로 읽을지 정합니다. 처리 중인 서류는 시작할 때의 설정으로 끝나고, 지원서마다 읽은 설정이 남습니다. 그림은 LLM에 보내지 않습니다.',
  },
  {
    key: 'audio',
    title: '음성 입력',
    description:
      '실시간 면접 마이크 음성에서 말소리 구간만 STT에 넣고(VAD), 지원자가 답변을 마쳤는지 판단합니다. 음성은 서버 밖으로 나가지 않습니다. 진행 중인 면접은 시작할 때의 설정을 씁니다.',
  },
]

const editing = ref<ModelRoleState | null>(null)
const dialogOpen = ref(false)

function edit(state: ModelRoleState) {
  editing.value = state
  dialogOpen.value = true
}
</script>

<template>
  <Page>
    <PageHeader
      eyebrow="관리자"
      title="모델 설정"
      description="역할마다 AI 모델과 서류 읽기 도구를 고르고, 테스트하고, 서버 재시작 없이 적용합니다."
    >
      <template v-if="settings.data" #actions>
        <Badge variant="outline" class="tabular">설정 rev {{ settings.data.revision }}</Badge>
      </template>
    </PageHeader>

    <EmptyState
      v-if="me.data && !isAdmin"
      :icon="LockIcon"
      title="관리자만 볼 수 있습니다"
      description="모델 설정은 관리자 권한이 있는 계정에서만 바꿀 수 있습니다."
    />
    <template v-else>
      <div
        v-if="settings.data && !settings.data.persistent"
        class="mb-4 flex items-start gap-2 rounded-lg border border-[color-mix(in_oklch,var(--warning)_40%,transparent)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] px-4 py-3 text-[13px]"
        role="alert"
      >
        <TriangleAlertIcon class="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
        모델 설정 테이블이 없어 바꿀 수 없습니다. 서버에서 <code class="font-mono">uv run alembic upgrade head</code>를 실행하세요.
      </div>

      <ErrorState v-if="settings.isError" :error="settings.error" @retry="settings.refetch()" />
      <template v-else>
        <section v-for="g in GROUPS" :key="g.key" :aria-labelledby="`group-${g.key}`" class="mb-8">
          <h2 :id="`group-${g.key}`" class="text-[15px] font-semibold tracking-tight">{{ g.title }}</h2>
          <p class="mt-0.5 mb-3 text-xs text-muted-foreground">{{ g.description }}</p>
          <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3" :data-testid="`group-${g.key}`">
            <template v-if="settings.data">
              <RoleCard v-for="r in settings.data.roles.filter((x) => (x.group ?? 'ai') === g.key)" :key="r.role" :state="r" @change="edit(r)" />
            </template>
            <template v-else>
              <Skeleton v-for="i in 3" :key="i" class="h-52 rounded-xl" />
            </template>
          </div>
          <EmbeddingIndexPanel v-if="g.key === 'ai' && isAdmin" class="mt-4" />
        </section>
      </template>

      <h2 class="mt-10 mb-3 text-[15px] font-semibold tracking-tight">변경 이력</h2>
      <Card class="overflow-hidden">
        <ErrorState v-if="history.isError" :error="history.error" @retry="history.refetch()" />
        <div v-else-if="!history.data" class="space-y-2 p-4">
          <Skeleton v-for="i in 4" :key="i" class="h-10" />
        </div>
        <ModelHistory v-else :changes="history.data" :catalog="catalog.data ?? []" />
      </Card>
    </template>

    <ChangeModelDialog :open="dialogOpen" :state="editing" :catalog="catalog.data ?? []" @close="dialogOpen = false" />
  </Page>
</template>
