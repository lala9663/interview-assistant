<script setup lang="ts">
import { MicIcon, MicOffIcon, PlayIcon, ShieldCheckIcon } from '@lucide/vue'
import { RadioGroupItem, RadioGroupRoot } from 'reka-ui'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { useSessionLifecycle } from '@/api/queries'
import type { SessionDetail } from '@/api/types'
import ModeBadge from '@/components/common/ModeBadge.vue'
import Page from '@/components/common/Page.vue'
import Pseudonym from '@/components/common/Pseudonym.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ROLE_LABEL } from '@/lib/labels'
import { formatDateTime, formatRelative } from '@/lib/time'

import CandidateSummary from './CandidateSummary.vue'
import PreStartStep from './PreStartStep.vue'

/** Before the interview: recording consent (FR-05, 녹음 동의) and start. */
const props = defineProps<{ detail: SessionDetail }>()
const emit = defineEmits<{ started: [] }>()

const lifecycle = useSessionLifecycle(props.detail.session.id)
const candidate = computed(() => props.detail.card.candidate)
const choice = ref<'yes' | 'no' | undefined>(candidate.value.consent_at !== null ? (candidate.value.consent_recording ? 'yes' : 'no') : undefined)
const consentSaved = computed(() => lifecycle.consent.isSuccess || candidate.value.consent_at !== null)
const consented = computed(() => candidate.value.consent_recording)

const OPTIONS = [
  { v: 'yes', icon: MicIcon, title: '동의함', desc: '녹음과 실시간 전사, 꼬리질문 제안을 켭니다' },
  { v: 'no', icon: MicOffIcon, title: '동의하지 않음', desc: '녹음 없이 답변을 수기로 기록합니다' },
] as const

const recordConsent = () => lifecycle.consent.mutate(choice.value === 'yes')
// mutateAsync: once started, this step view is replaced before per-call mutate callbacks would run.
const start = () =>
  lifecycle.start.mutateAsync().then(
    () => emit('started'),
    () => {},
  )
</script>

<template>
  <Page class="max-w-[1100px]">
    <div class="mb-6">
      <p class="text-xs font-medium text-muted-foreground">
        면접 준비 · {{ detail.session.scheduled_at ? formatDateTime(detail.session.scheduled_at) : '' }}
      </p>
      <h1 class="mt-1 flex flex-wrap items-center gap-3 text-[22px] font-semibold tracking-tight">
        <Pseudonym :value="candidate.pseudonym" size="lg" />
        <span class="text-base font-normal text-muted-foreground">{{ detail.posting.title }}</span>
      </h1>
    </div>
    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card>
        <CardContent class="pt-5">
          <ol class="relative before:absolute before:top-2 before:bottom-2 before:left-[13px] before:w-px before:bg-border">
            <PreStartStep :n="1" title="녹음·전사 동의 확인" :done="consentSaved">
              <p class="mb-3 text-[13px] leading-relaxed text-muted-foreground">
                녹음과 실시간 전사는 지원자의 사전 동의가 있을 때만 합니다. 동의하지 않으면 녹음 없이 수기 모드로 진행합니다.
              </p>
              <RadioGroupRoot v-model="choice" class="grid gap-2 sm:grid-cols-2" aria-label="녹음 동의 여부">
                <RadioGroupItem
                  v-for="o in OPTIONS"
                  :key="o.v"
                  :value="o.v"
                  class="flex items-start gap-3 rounded-lg border bg-card p-3 text-left transition-colors outline-none hover:bg-subtle focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=checked]:border-ring data-[state=checked]:bg-brand-soft"
                >
                  <component :is="o.icon" class="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <span>
                    <span class="block text-[13px] font-medium">{{ o.title }}</span>
                    <span class="block text-xs text-muted-foreground">{{ o.desc }}</span>
                  </span>
                </RadioGroupItem>
              </RadioGroupRoot>
              <div class="mt-3 flex items-center gap-3">
                <Button size="sm" :variant="consentSaved ? 'outline' : 'default'" :disabled="!choice || lifecycle.consent.isPending" @click="recordConsent">
                  <ShieldCheckIcon />
                  {{ consentSaved ? '동의 다시 기록' : '동의 여부 기록' }}
                </Button>
                <span v-if="consentSaved" class="text-xs text-muted-foreground">
                  {{
                    consented
                      ? `동의 기록됨 · ${candidate.consent_at ? formatRelative(candidate.consent_at) : ''}`
                      : '미동의 기록됨 · 수기 모드'
                  }}
                </span>
              </div>
            </PreStartStep>
            <PreStartStep :n="2" title="면접 준비 확인" :done="consentSaved">
              <ul class="space-y-1.5 text-[13px]">
                <li class="flex items-center gap-2">
                  <ModeBadge :mode="detail.session.mode" />
                  <span class="text-muted-foreground">
                    {{ detail.session.mode === 'remote' ? '앱 내 통화는 11단계에서 연결됩니다 (모의 모드에서는 전사만 재생)' : '방 안 마이크 1대 기준' }}
                  </span>
                </li>
                <li class="flex flex-wrap items-center gap-1.5">
                  <span class="text-muted-foreground">면접관</span>
                  <Badge v-for="p in detail.interviewers" :key="p.interviewer_id" variant="outline">{{ p.interviewer.name }} · {{ ROLE_LABEL[p.role] }}</Badge>
                </li>
                <li class="text-muted-foreground">
                  사전 질문 {{ detail.preset_questions.length }}개 · 역량 {{ detail.competency_set?.competencies.length ?? 0 }}개
                  <template v-if="detail.competency_set"> (역량 사전 v{{ detail.competency_set.version }})</template>
                </li>
              </ul>
            </PreStartStep>
            <PreStartStep :n="3" title="면접 시작" :done="false">
              <p class="mb-3 text-[13px] text-muted-foreground">
                {{
                  consentSaved
                    ? consented
                      ? '시작하면 녹음과 실시간 전사가 켜집니다.'
                      : '시작하면 녹음 없이 수기 모드로 진행합니다.'
                    : '먼저 동의 여부를 기록하세요.'
                }}
              </p>
              <div class="flex gap-2">
                <Button :disabled="!consentSaved || lifecycle.start.isPending" @click="start">
                  <PlayIcon />
                  {{ lifecycle.start.isPending ? '시작하는 중…' : '면접 시작' }}
                </Button>
                <Button as-child variant="ghost">
                  <RouterLink to="/sessions">나중에</RouterLink>
                </Button>
              </div>
            </PreStartStep>
          </ol>
        </CardContent>
      </Card>
      <Card>
        <CardContent class="pt-5">
          <CandidateSummary :card="detail.card" />
        </CardContent>
      </Card>
    </div>
  </Page>
</template>
