<script setup lang="ts">
import { ArrowRightIcon, BotIcon, BriefcaseIcon, CalendarIcon, FolderGit2Icon, GraduationCapIcon } from '@lucide/vue'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { toast } from 'vue-sonner'

import { useApplication, useUpdateScreening } from '@/api/queries'
import { SCREENING_STATUSES, type ScreeningStatus } from '@/api/types'
import DeidText from '@/components/common/DeidText.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import FitRing from '@/components/common/FitRing.vue'
import PrivacyNote from '@/components/common/PrivacyNote.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import SessionStatusBadge from '@/components/common/SessionStatusBadge.vue'
import { Badge } from '@/components/ui/badge'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Separator } from '@/components/ui/separator'
import { SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { parseRationale, SCREENING_STATUS_LABEL } from '@/lib/labels'
import { formatDate, formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'

import SheetSection from './SheetSection.vue'

const props = defineProps<{ applicationId: string; postingId: string }>()

const q = useApplication(() => props.applicationId)
const update = useUpdateScreening(() => props.postingId)
const rationale = computed(() => (q.data?.screening ? parseRationale(q.data.screening.rationale) : null))

const change = (status: string) => {
  const d = q.data
  if (!d?.screening || status === d.screening.status) return
  const next = status as ScreeningStatus
  update.mutate(
    { screeningId: d.screening.id, status: next },
    {
      onSuccess: () => toast.success(`${d.candidate.pseudonym} → ${SCREENING_STATUS_LABEL[next]}`, { description: '변경 내역은 감사 로그에 남습니다.' }),
      onError: toastError('상태를 바꾸지 못했습니다'),
    },
  )
}
</script>

<template>
  <div v-if="q.isError">
    <SheetTitle class="sr-only">지원자 상세</SheetTitle>
    <SheetDescription class="sr-only">지원서를 불러오지 못했습니다.</SheetDescription>
    <ErrorState :error="q.error" @retry="q.refetch()" />
  </div>
  <div v-else-if="!q.data" class="space-y-4 p-6">
    <SheetTitle class="sr-only">지원자 상세</SheetTitle>
    <SheetDescription class="sr-only">지원서를 불러오는 중입니다.</SheetDescription>
    <Skeleton class="h-14 w-60" />
    <Skeleton class="h-9 w-72" />
    <Skeleton class="h-32" />
    <Skeleton class="h-48" />
  </div>
  <div v-else class="space-y-6 p-6">
    <div class="flex items-center gap-4 pr-8">
      <FitRing v-if="q.data.screening" :value="q.data.screening.fit_score" :size="60" />
      <div class="min-w-0">
        <SheetTitle as-child>
          <h2><Pseudonym :value="q.data.candidate.pseudonym" size="lg" /></h2>
        </SheetTitle>
        <SheetDescription class="mt-0.5 truncate">{{ q.data.posting.title }} · 접수 {{ formatDate(q.data.application.created_at) }}</SheetDescription>
      </div>
    </div>

    <div v-if="q.data.screening" class="space-y-2">
      <div class="flex items-center justify-between gap-3">
        <span class="text-[13px] font-medium">선별 상태</span>
        <Segmented :model-value="q.data.screening.status" aria-label="선별 상태 변경" :disabled="update.isPending" @update:model-value="change">
          <SegmentedItem v-for="s in SCREENING_STATUSES" :key="s" :value="s">{{ SCREENING_STATUS_LABEL[s] }}</SegmentedItem>
        </Segmented>
      </div>
      <p class="text-xs text-muted-foreground">AI 적합도는 참고용입니다. 통과·보류·탈락은 사람이 확정하고, 바꾼 내역은 감사 로그에 남습니다.</p>
    </div>

    <SheetSection v-if="rationale && q.data.screening" title="선별 근거" :icon="BotIcon">
      <div class="rounded-lg border bg-subtle p-4">
        <p class="text-[13.5px] leading-relaxed"><DeidText :text="rationale.summary" /></p>
        <ul v-if="rationale.strengths.length > 0" class="mt-3 space-y-1.5 text-[13px]">
          <li v-for="s in rationale.strengths" :key="s" class="flex gap-2">
            <span class="font-semibold text-success" aria-label="강점">+</span>
            <DeidText :text="s" />
          </li>
        </ul>
        <ul v-if="rationale.concerns.length > 0" class="mt-2 space-y-1.5 text-[13px] text-muted-foreground">
          <li v-for="s in rationale.concerns" :key="s" class="flex gap-2">
            <span class="font-semibold text-warning" aria-label="확인 필요">−</span>
            <DeidText :text="s" />
          </li>
        </ul>
        <p class="mt-3 font-mono text-[11px] text-muted-foreground">
          {{ q.data.screening.model }} · {{ q.data.screening.prompt_version }} · {{ formatDateTime(q.data.screening.created_at) }}
        </p>
      </div>
    </SheetSection>

    <template v-if="q.data.application.profile">
      <Separator />
      <SheetSection title="구조화 프로필">
        <p class="text-[13.5px] leading-relaxed"><DeidText :text="q.data.application.profile.summary" /></p>
        <div class="flex flex-wrap gap-1">
          <Badge variant="outline">경력 {{ q.data.application.profile.years_experience }}년</Badge>
          <Badge v-for="s in q.data.application.profile.skills" :key="s" variant="secondary">{{ s }}</Badge>
        </div>
      </SheetSection>
      <SheetSection title="경력" :icon="BriefcaseIcon">
        <ol class="relative space-y-4 border-l pl-4">
          <li v-for="e in q.data.application.profile.experience" :key="e.company + e.period" class="relative">
            <span class="absolute top-1.5 -left-[21px] size-2.5 rounded-full border-2 border-card bg-muted-foreground/60" aria-hidden="true"></span>
            <p class="text-[13.5px] font-medium"><DeidText :text="e.company" /> · {{ e.role }}</p>
            <p class="text-xs text-muted-foreground">{{ e.period }}</p>
            <ul class="mt-1.5 list-disc space-y-0.5 pl-4 text-[13px] text-muted-foreground marker:text-muted-foreground/50">
              <li v-for="h in e.highlights" :key="h"><DeidText :text="h" /></li>
            </ul>
          </li>
        </ol>
      </SheetSection>
      <div class="grid gap-6 sm:grid-cols-2">
        <SheetSection title="학력" :icon="GraduationCapIcon">
          <p v-for="e in q.data.application.profile.education" :key="e.school + e.major" class="text-[13px]">
            <DeidText :text="e.school" /> <span class="text-muted-foreground">{{ e.degree }} · {{ e.major }}</span>
          </p>
        </SheetSection>
        <SheetSection title="자격">
          <p class="text-[13px] text-muted-foreground">
            {{ q.data.application.profile.certifications.length > 0 ? q.data.application.profile.certifications.join(', ') : '없음' }}
          </p>
        </SheetSection>
      </div>
      <SheetSection v-if="q.data.application.profile.projects.length > 0" title="프로젝트" :icon="FolderGit2Icon">
        <div v-for="pr in q.data.application.profile.projects" :key="pr.name" class="rounded-lg border p-3">
          <p class="text-[13px] font-medium">{{ pr.name }}</p>
          <p class="mt-0.5 text-[13px] text-muted-foreground"><DeidText :text="pr.description" /></p>
          <div class="mt-2 flex flex-wrap gap-1">
            <Badge v-for="t in pr.tech" :key="t" variant="outline">{{ t }}</Badge>
          </div>
        </div>
      </SheetSection>
    </template>

    <Separator />
    <SheetSection title="면접" :icon="CalendarIcon">
      <p v-if="q.data.sessions.length === 0" class="text-[13px] text-muted-foreground">
        잡힌 면접이 없습니다. 통과 처리 후 면접관 스케줄에서 일정을 잡을 수 있습니다.
      </p>
      <ul v-else class="space-y-1.5">
        <li v-for="s in q.data.sessions" :key="s.id">
          <RouterLink
            :to="s.status === 'completed' ? `/sessions/${s.id}/evaluation` : `/sessions/${s.id}/live`"
            class="flex items-center gap-3 rounded-lg border px-3 py-2 text-[13px] transition-colors hover:bg-subtle"
          >
            <SessionStatusBadge :status="s.status" />
            <span>{{ s.scheduled_at ? formatDateTime(s.scheduled_at) : '' }}</span>
            <ArrowRightIcon class="ml-auto size-4 text-muted-foreground" aria-hidden="true" />
          </RouterLink>
        </li>
      </ul>
    </SheetSection>
    <PrivacyNote />
  </div>
</template>
