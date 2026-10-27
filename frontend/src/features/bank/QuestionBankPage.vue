<script setup lang="ts">
import { LibraryBigIcon, RulerIcon } from '@lucide/vue'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useMe } from '@/api/queries'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import QuestionBankTab from './QuestionBankTab.vue'
import RubricTab from './RubricTab.vue'

/**
 * 질문 은행 · 평점 기준 예시: company-written text that retrieval works on. Only approved items are searched
 * (follow-up suggestions, examples for the AI) or shown to the scoring model; applicants' answers never are.
 */
const me = useMe()
const isAdmin = computed(() => me.data?.is_admin === true)
const route = useRoute()
const router = useRouter()
const tab = computed({
  get: () => (route.query.tab === 'rubric' ? 'rubric' : 'bank'),
  set: (v: string) => void router.replace({ query: { ...route.query, tab: v === 'rubric' ? 'rubric' : undefined } }),
})
</script>

<template>
  <Page>
    <PageHeader
      eyebrow="면접 준비"
      title="질문 은행·평점 기준"
      description="직군·역량별로 채용 담당자가 검수한 질문과, 점수마다 수준을 보여 주는 가상 답변입니다. 승인한 것만 꼬리질문 후보·AI 예시·채점 기준점으로 쓰입니다."
    />
    <Tabs :model-value="tab" @update:model-value="(v) => (tab = String(v))">
      <TabsList>
        <TabsTrigger value="bank">
          <LibraryBigIcon class="size-3.5" aria-hidden="true" />
          질문 은행
        </TabsTrigger>
        <TabsTrigger value="rubric">
          <RulerIcon class="size-3.5" aria-hidden="true" />
          평점 기준 예시
        </TabsTrigger>
      </TabsList>
      <TabsContent value="bank" class="mt-4">
        <QuestionBankTab :is-admin="isAdmin" />
      </TabsContent>
      <TabsContent value="rubric" class="mt-4">
        <RubricTab :is-admin="isAdmin" />
      </TabsContent>
    </Tabs>
  </Page>
</template>
