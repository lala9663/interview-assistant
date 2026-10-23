<script setup lang="ts">
import { CalendarXIcon, CircleCheckBigIcon } from '@lucide/vue'
import { useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { qk, useSession } from '@/api/queries'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import Page from '@/components/common/Page.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

import LiveRoom from './LiveRoom.vue'
import PreStart from './PreStart.vue'

const route = useRoute()
const sessionId = computed(() => String(route.params.sessionId ?? ''))
const session = useSession(sessionId)
const qc = useQueryClient()
const onStarted = () => void qc.invalidateQueries({ queryKey: qk.session(sessionId.value) })
</script>

<template>
  <Page v-if="session.isError">
    <ErrorState :error="session.error" @retry="session.refetch()" />
  </Page>
  <div v-else-if="!session.data" class="flex h-[calc(100vh-3.5rem)] flex-col">
    <div class="flex h-14 items-center gap-3 border-b px-4">
      <Skeleton class="h-5 w-24" />
      <Skeleton class="h-4 w-48" />
      <Skeleton class="ml-auto h-8 w-40" />
    </div>
    <div class="grid flex-1 grid-cols-[300px_1fr_380px] gap-0">
      <div class="space-y-3 border-r p-4">
        <Skeleton class="h-24" />
        <Skeleton class="h-40" />
      </div>
      <div class="space-y-3 p-5">
        <Skeleton v-for="i in 5" :key="i" class="h-14" />
      </div>
      <div class="space-y-3 border-l p-4">
        <Skeleton class="h-28" />
        <Skeleton class="h-28" />
      </div>
    </div>
  </div>
  <PreStart v-else-if="session.data.session.status === 'scheduled'" :detail="session.data" @started="onStarted" />
  <LiveRoom v-else-if="session.data.session.status === 'in_progress'" :key="session.data.session.id" :detail="session.data" />
  <Page v-else-if="session.data.session.status === 'completed'">
    <EmptyState :icon="CircleCheckBigIcon" title="종료된 면접입니다" description="Q&A와 AI 참고 점수, 면접관 점수는 평가 화면에서 확인합니다.">
      <template #action>
        <div class="flex gap-2">
          <Button as-child>
            <RouterLink :to="`/sessions/${sessionId}/evaluation`">평가 보기</RouterLink>
          </Button>
          <Button as-child variant="outline">
            <RouterLink to="/sessions">면접 목록</RouterLink>
          </Button>
        </div>
      </template>
    </EmptyState>
  </Page>
  <Page v-else>
    <EmptyState :icon="CalendarXIcon" title="취소된 면접입니다">
      <template #action>
        <Button as-child variant="outline">
          <RouterLink to="/sessions">면접 목록</RouterLink>
        </Button>
      </template>
    </EmptyState>
  </Page>
</template>
