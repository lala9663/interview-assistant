<script setup lang="ts">
import { ArrowLeftIcon, BookCheckIcon, FileSearchIcon, FileTextIcon } from '@lucide/vue'
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { usePosting } from '@/api/queries'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { POSTING_STATUS_LABEL } from '@/lib/labels'

import CompetencySection from './CompetencySection.vue'

const route = useRoute()
const postingId = computed(() => String(route.params.postingId ?? ''))
const q = usePosting(postingId)
</script>

<template>
  <Page v-if="q.isError">
    <ErrorState :error="q.error" @retry="q.refetch()" />
  </Page>
  <Page v-else-if="!q.data">
    <Skeleton class="mb-2 h-3 w-24" />
    <Skeleton class="mb-6 h-7 w-80" />
    <Skeleton class="h-96" />
  </Page>
  <Page v-else>
    <PageHeader :title="q.data.title">
      <template #eyebrow>
        <RouterLink to="/postings" class="inline-flex items-center gap-1 hover:text-foreground">
          <ArrowLeftIcon class="size-3.5" aria-hidden="true" />
          공고·역량 사전
        </RouterLink>
      </template>
      <template #description>
        <span class="flex flex-wrap items-center gap-2">
          <span>{{ q.data.job_family }}</span>
          <Badge :variant="q.data.status === 'open' ? 'success' : 'outline'">{{ POSTING_STATUS_LABEL[q.data.status] }}</Badge>
          <span>
            지원 {{ q.data.counts.applications }} · 통과 {{ q.data.counts.passed }} · 면접
            {{ q.data.counts.interviewing + q.data.counts.interviewed }}
          </span>
        </span>
      </template>
      <template #actions>
        <Button as-child variant="outline" size="sm">
          <RouterLink :to="`/screening/${q.data.id}`">
            <FileSearchIcon />
            서류 선별 보기
          </RouterLink>
        </Button>
      </template>
    </PageHeader>
    <Tabs default-value="competency">
      <TabsList>
        <TabsTrigger value="competency">
          <BookCheckIcon />
          역량 사전
        </TabsTrigger>
        <TabsTrigger value="jd">
          <FileTextIcon />
          JD 원문
        </TabsTrigger>
      </TabsList>
      <TabsContent value="competency" class="mt-4">
        <CompetencySection :posting-id="q.data.id" />
      </TabsContent>
      <TabsContent value="jd" class="mt-4">
        <Card>
          <CardContent class="pt-5">
            <pre class="font-sans text-[14px] leading-[1.8] whitespace-pre-wrap">{{ q.data.jd_text }}</pre>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </Page>
</template>
