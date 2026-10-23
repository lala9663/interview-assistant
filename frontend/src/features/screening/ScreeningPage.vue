<script setup lang="ts">
import { FileSearchIcon, UploadIcon } from '@lucide/vue'
import { computed, ref, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useApplications, usePostings } from '@/api/queries'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import PrivacyNote from '@/components/common/PrivacyNote.vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'

import ApplicationSheet from './ApplicationSheet.vue'
import ScreeningTable from './ScreeningTable.vue'
import UploadDialog from './UploadDialog.vue'

const route = useRoute()
const router = useRouter()
const postings = usePostings()
const postingId = computed(() => (typeof route.params.postingId === 'string' ? route.params.postingId : ''))
const apps = useApplications(postingId)
const selected = computed(() => (typeof route.query.app === 'string' ? route.query.app : null))
const posting = computed(() => postings.data?.find((p) => p.id === postingId.value))

// /screening without a posting: open the first posting that has applications.
watchEffect(() => {
  if (postingId.value || !postings.data) return
  const first = postings.data.find((p) => p.counts.applications > 0) ?? postings.data[0]
  if (first) void router.replace(`/screening/${first.id}`)
})

const open = (id: string) => void router.replace({ query: { ...route.query, app: id } })
const close = () => {
  const { app: _, ...rest } = route.query
  void router.replace({ query: rest })
}
const pick = (v: unknown) => {
  if (typeof v === 'string' && v) void router.push(`/screening/${v}`)
}
const uploading = ref(false)
</script>

<template>
  <template v-if="!postingId">
    <Page v-if="postings.isError"><ErrorState :error="postings.error" @retry="postings.refetch()" /></Page>
    <Page v-else><Skeleton class="h-96" /></Page>
  </template>
  <Page v-else>
    <PageHeader eyebrow="FR-01 · FR-03" title="서류 선별" description="JD와 확정된 역량 사전 기준의 AI 적합도와 근거입니다. 통과·보류·탈락은 사람이 확정합니다.">
      <template #actions>
        <Select :model-value="postingId" @update:model-value="pick">
          <SelectTrigger class="w-80" aria-label="공고 선택">
            <SelectValue placeholder="공고 선택" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="p in postings.data ?? []" :key="p.id" :value="p.id">{{ p.title }} · {{ p.counts.applications }}명</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" :disabled="!posting || posting.status === 'closed'" @click="uploading = true">
          <UploadIcon />
          서류 업로드
        </Button>
      </template>
    </PageHeader>
    <ErrorState v-if="apps.isError" :error="apps.error" @retry="apps.refetch()" />
    <Card v-else-if="!apps.data" class="space-y-3 p-4">
      <Skeleton class="h-8 w-80" />
      <Skeleton v-for="i in 8" :key="i" class="h-10" />
    </Card>
    <Card v-else-if="apps.data.length === 0">
      <EmptyState
        :icon="FileSearchIcon"
        title="아직 지원서가 없습니다"
        :description="
          posting?.status === 'draft'
            ? '공고가 작성 중입니다. 역량 사전을 확정하고 공고를 열면 서류 선별이 시작됩니다.'
            : '지원서가 들어오면 AI가 적합도와 근거를 붙여 이곳에 보여 줍니다.'
        "
      />
    </Card>
    <ScreeningTable v-else :rows="apps.data" :selected-id="selected" @open="open" />
    <PrivacyNote class="mt-3" />
    <ApplicationSheet :application-id="selected" :posting-id="postingId" @close="close" />
    <UploadDialog
      :open="uploading"
      :posting-id="postingId"
      :posting-title="posting?.title ?? ''"
      @close="uploading = false"
      @uploaded="(r) => ((uploading = false), open(r.application_id))"
    />
  </Page>
</template>
