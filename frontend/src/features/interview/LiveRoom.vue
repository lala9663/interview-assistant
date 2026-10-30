<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { qk, useAnswerQA, useCarryover, useCreateNote, useCreateQA, useSessionLifecycle } from '@/api/queries'
import type { CreateQARequest, PresetQuestion, QAItem, SessionDetail } from '@/api/types'
import { interviewMode } from '@/components/layout/interview-mode'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { clockPhase, DEFAULT_PLANNED_MINUTES, elapsedMs } from '@/lib/session-clock'
import { MINUTE } from '@/lib/time'
import { errorMessage, toastError } from '@/lib/toast'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

import CandidateSummary from './CandidateSummary.vue'
import ConnectionBanner from './ConnectionBanner.vue'
import CurrentQuestion, { type AnswerState } from './CurrentQuestion.vue'
import FollowUpPanel from './FollowUpPanel.vue'
import { useFollowUps, type Suggestion } from './follow-ups'
import LiveHeader from './LiveHeader.vue'
import LongOpenBanner from './LongOpenBanner.vue'
import ManualAnswerBox from './ManualAnswerBox.vue'
import ManualLog from './ManualLog.vue'
import MicPanel from './MicPanel.vue'
import NotesPanel from './NotesPanel.vue'
import PresetQuestions from './PresetQuestions.vue'
import QuestionComposer from './QuestionComposer.vue'
import { useRoomLayout, type RoomLayout } from './room-layout'
import TranscriptView from './TranscriptView.vue'
import { useTranscript, type AnsweredEvent } from './use-transcript'

const props = defineProps<{ detail: SessionDetail }>()

const sessionId = props.detail.session.id
const router = useRouter()
const qc = useQueryClient()
const manual = !props.detail.session.has_recording
const { state: followUps, request: requestFollowUps, markUsed } = useFollowUps(sessionId)
const createQA = useCreateQA(sessionId)
const answerQA = useAnswerQA(sessionId)
const createNote = useCreateNote(sessionId)
const carryover = useCarryover(sessionId)
const { end } = useSessionLifecycle(sessionId)
const earlierLabel = computed(() => props.detail.card.previous_rounds.at(-1)?.round.label ?? null)
const makeCarryover = () =>
  carryover.mutate(undefined, {
    onSuccess: (d) => toast.success(`이어 질문 ${d.carryover_questions.length}개를 만들었습니다`, { description: `${earlierLabel.value}에서 물은 질문은 반복하지 않습니다.` }),
    onError: toastError('이어 질문을 만들지 못했습니다'),
  })
const editedIds = ref<ReadonlySet<string>>(new Set())
const pendingPreset = ref<string | null>(null)
const pendingSuggestion = ref<string | null>(null)

// 면접 모드: the app's menu folds away while this room is open (the header brings it back).
interviewMode.enter()
onBeforeUnmount(() => interviewMode.leave())

// Three columns when the room is wide enough, else 지원자 and 사전 질문 become tabs beside 꼬리질문.
const room = ref<HTMLElement>()
const layout = useRoomLayout(room)
const GRID: Record<RoomLayout, string> = {
  wide: 'grid-cols-[clamp(250px,22%,320px)_minmax(0,1fr)_clamp(320px,28%,420px)]',
  medium: 'grid-cols-[minmax(0,1fr)_clamp(300px,36%,380px)]',
  narrow: 'grid-cols-1',
}
type Tab = 'next' | 'presets' | 'candidate'
const tab = ref<Tab>('next')
// Wide: the left column's own tabs, 사전 질문 first (the candidate was read before starting).
const sideTab = ref<Exclude<Tab, 'next'>>('presets')
watch(layout, (l) => {
  if (l === 'wide') tab.value = 'next'
})

const qaItems = computed(() => props.detail.qa_items)
const latest = computed(() => qaItems.value[qaItems.value.length - 1])
const presetsAsked = computed(
  () => props.detail.preset_questions.filter((p) => qaItems.value.some((q) => q.question_source === 'preset' && q.question === p.question)).length,
)
// Cards waiting to be picked while another tab is open: a dot on the 꼬리질문 tab.
const freshFollowUps = computed(() => !followUps.value.used && followUps.value.suggestions.some((s) => s.duplicateOf === null))

// Only the newest question's answer triggers suggestions (an older answer finishing late does not).
const onAnswered = (e: AnsweredEvent) => {
  if (latest.value?.id === e.qa_item_id) void requestFollowUps(e.qa_item_id)
}
const { state: transcript, reconnect } = useTranscript(sessionId, !manual, onAnswered)

// Reopened page after an answer finished: offer follow-ups for it right away.
let autoRequested = false
watch(
  [latest, () => followUps.value.status],
  () => {
    const l = latest.value
    if (autoRequested || followUps.value.status !== 'idle' || !l?.answer_deidentified) return
    autoRequested = true
    void requestFollowUps(l.id)
  },
  { immediate: true },
)

const answeringId = computed(() => (latest.value && !latest.value.answer_deidentified ? latest.value.id : null))
// The stream failed, or the server cannot transcribe (no VAD, no STT model ...): answers are typed.
const sttDown = computed(() => !manual && (transcript.value.connection === 'error' || transcript.value.status?.stt === 'down'))
const listening = computed(() => !manual && !sttDown.value && answeringId.value !== null)
const answerState = computed<AnswerState>(() => {
  if (latest.value?.answer_deidentified) return 'answered'
  if (listening.value) return 'listening'
  return manual || sttDown.value ? 'typing' : 'waiting'
})

// Left open far past its plan (lib/session-clock.ts): a banner asks to end it; "later" waits an hour.
const now = useNow(15_000)
const elapsed = computed(() => elapsedMs(props.detail.session.started_at, now.value))
const snoozedUntil = ref(0)
const longOpen = computed(() => clockPhase(elapsed.value) === 'long_open' && elapsed.value >= snoozedUntil.value)
const snooze = () => (snoozedUntil.value = elapsed.value + 60 * MINUTE)
const endOpen = ref(false)

const setDetail = (fn: (d: SessionDetail) => SessionDetail) =>
  qc.setQueryData<SessionDetail>(qk.session(sessionId), (d) => (d ? fn(d) : d))
const appendQA = (qa: QAItem) => setDetail((d) => (d.qa_items.some((x) => x.id === qa.id) ? d : { ...d, qa_items: [...d.qa_items, qa] }))

function ask(body: CreateQARequest, opts: { onDone?: (qa: QAItem) => void; finally?: () => void } = {}) {
  createQA.mutate(body, {
    onSuccess: (qa) => {
      appendQA(qa)
      opts.onDone?.(qa)
    },
    onError: (e) => toast.error('질문을 기록하지 못했습니다', { description: errorMessage(e) }),
    onSettled: opts.finally,
  })
}

function askPreset(p: PresetQuestion) {
  pendingPreset.value = p.id
  ask({ question: p.question, question_source: 'preset', preset_question_id: p.id }, { finally: () => (pendingPreset.value = null) })
}

/** Follow-ups are never asked automatically: only the one the interviewer picks (or edits) is recorded. */
function applySuggestion(s: Suggestion, text: string, edited: boolean) {
  const batchId = followUps.value.batchId
  if (!batchId) return
  pendingSuggestion.value = s.id
  ask(
    {
      question: text,
      question_source: 'ai_suggested',
      suggestion: { batch_id: batchId, suggestion_id: s.id, edited, original_question: s.text },
    },
    {
      onDone: (qa) => {
        markUsed(s.id, qa.seq, edited)
        if (edited) editedIds.value = new Set(editedIds.value).add(qa.id)
        const what = s.source === 'bank' ? '질문 은행 후보' : 'AI 제안'
        toast.success(`Q${qa.seq}로 기록했습니다`, { description: edited ? `${what}를 수정해 사용했습니다.` : `${what}를 그대로 사용했습니다.` })
      },
      finally: () => (pendingSuggestion.value = null),
    },
  )
}

function saveManualAnswer(qa: QAItem, answer: string) {
  answerQA.mutate(
    { qaId: qa.id, answer },
    {
      onSuccess: (updated) => {
        setDetail((d) => ({ ...d, qa_items: d.qa_items.map((x) => (x.id === updated.id ? updated : x)) }))
        void requestFollowUps(updated.id)
      },
      onError: (e) => toast.error('답변을 저장하지 못했습니다', { description: errorMessage(e) }),
    },
  )
}

async function saveNote(content: string): Promise<boolean> {
  try {
    await createNote.mutateAsync(content)
    return true
  } catch (e) {
    toast.error('메모를 저장하지 못했습니다', { description: errorMessage(e) })
    return false
  }
}

// mutateAsync, not mutate callbacks: the ended session swaps this room out of the page before
// per-call callbacks would run, and TanStack Query skips those for unmounted observers.
async function onEnd() {
  try {
    await end.mutateAsync()
  } catch (e) {
    toast.error('면접을 종료하지 못했습니다', { description: errorMessage(e) })
    return
  }
  toast.success('면접을 종료했습니다', { description: 'AI 채점을 시작했습니다. 면접관 점수를 입력하세요.' })
  void router.push(`/sessions/${sessionId}/evaluation`)
}

const retryFollowUps = () => {
  const id = followUps.value.qaItemId
  if (id) void requestFollowUps(id)
}

const followUpProps = computed(() => ({
  state: followUps.value,
  listening: listening.value,
  hasAnswer: Boolean(followUps.value.qaItemId),
  disabled: createQA.isPending,
  pendingSuggestionId: pendingSuggestion.value,
  visible: layout.value === 'wide' || tab.value === 'next',
}))
const presetProps = computed(() => ({
  presets: props.detail.preset_questions,
  carryover: props.detail.carryover_questions,
  earlierLabel: earlierLabel.value,
  generating: carryover.isPending,
  qaItems: qaItems.value,
  disabled: createQA.isPending,
  pendingId: pendingPreset.value,
}))
</script>

<template>
  <div
    ref="room"
    :class="cn('flex flex-col', layout !== 'narrow' && (interviewMode.focused.value ? 'h-screen' : 'h-[calc(100vh-3.5rem)]'))"
    data-testid="live-room"
  >
    <LiveHeader
      v-model:end-open="endOpen"
      :detail="detail"
      :status="transcript.status"
      :connection="manual ? 'idle' : transcript.connection"
      :ending="end.isPending"
      @end="onEnd"
    />
    <LongOpenBanner
      v-if="longOpen"
      :elapsed-ms="elapsed"
      :planned-minutes="DEFAULT_PLANNED_MINUTES"
      :started-at="detail.session.started_at"
      @end="endOpen = true"
      @snooze="snooze"
    />
    <div :class="cn('grid min-h-0 flex-1', GRID[layout])" :data-layout="layout">
      <aside v-if="layout === 'wide'" class="flex min-h-0 flex-col border-r" aria-label="지원자와 사전 질문">
        <Tabs v-model="sideTab" :unmount-on-hide="false" class="flex min-h-0 flex-1 flex-col">
          <div class="px-4 pt-3">
            <TabsList class="w-full" aria-label="사전 질문과 지원자">
              <TabsTrigger value="presets" class="flex-1">
                사전 질문
                <span class="text-muted-foreground tabular">{{ presetsAsked }}/{{ detail.preset_questions.length }}</span>
              </TabsTrigger>
              <TabsTrigger value="candidate" class="flex-1">지원자</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="presets" class="min-h-0 flex-1 space-y-5 overflow-y-auto p-4 scrollbar-thin">
            <PresetQuestions v-bind="presetProps" @ask="askPreset" @generate="makeCarryover" />
          </TabsContent>
          <TabsContent value="candidate" class="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
            <CandidateSummary :card="detail.card" />
          </TabsContent>
        </Tabs>
      </aside>

      <section :class="cn('flex min-h-0 flex-col', layout === 'narrow' && 'h-[70vh]')" aria-label="트랜스크립트">
        <MicPanel :session-id="sessionId" :manual="manual" :status="transcript.status" @question="appendQA" />
        <ConnectionBanner v-if="!manual" :connection="transcript.connection" @reconnect="reconnect" />
        <CurrentQuestion v-if="latest" :qa="latest" :answer="answerState" />
        <ManualLog v-if="manual" :qa-items="qaItems" :edited-ids="editedIds" />
        <TranscriptView
          v-else
          :segments="transcript.segments"
          :partial="transcript.partial"
          :qa-items="qaItems"
          :listening="listening"
          :edited-ids="editedIds"
          :started-at="detail.session.started_at"
        />
        <ManualAnswerBox
          v-if="(manual || sttDown) && latest && !latest.answer_deidentified"
          :key="latest.id"
          :qa="latest"
          :pending="answerQA.isPending"
          @save="(a) => latest && saveManualAnswer(latest, a)"
        />
        <QuestionComposer :disabled="false" :pending="createQA.isPending" @submit="(text) => ask({ question: text, question_source: 'interviewer' })" />
      </section>

      <aside :class="cn('flex min-h-0 flex-col', layout === 'narrow' ? 'border-t' : 'border-l')" aria-label="다음 질문과 메모">
        <div v-if="layout === 'wide'" class="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
          <FollowUpPanel v-bind="followUpProps" @use="applySuggestion" @retry="retryFollowUps" />
        </div>
        <Tabs v-else v-model="tab" :unmount-on-hide="false" class="flex min-h-0 flex-1 flex-col">
          <div class="px-4 pt-3">
            <TabsList class="w-full" aria-label="다음 질문과 지원자">
              <TabsTrigger value="next" class="flex-1">
                꼬리질문
                <span v-if="freshFollowUps && tab !== 'next'" class="size-1.5 rounded-full bg-brand" data-testid="fresh-follow-ups">
                  <span class="sr-only">새 후보</span>
                </span>
              </TabsTrigger>
              <TabsTrigger value="presets" class="flex-1">
                사전 질문
                <span class="text-muted-foreground tabular">{{ presetsAsked }}/{{ detail.preset_questions.length }}</span>
              </TabsTrigger>
              <TabsTrigger value="candidate" class="flex-1">지원자</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="next" class="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
            <FollowUpPanel v-bind="followUpProps" @use="applySuggestion" @retry="retryFollowUps" @reveal="tab = 'next'" />
          </TabsContent>
          <TabsContent value="presets" class="min-h-0 flex-1 space-y-5 overflow-y-auto p-4 scrollbar-thin">
            <PresetQuestions v-bind="presetProps" @ask="askPreset" @generate="makeCarryover" />
          </TabsContent>
          <TabsContent value="candidate" class="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
            <CandidateSummary :card="detail.card" />
          </TabsContent>
        </Tabs>
        <div class="border-t p-3">
          <NotesPanel :notes="detail.notes" :panel="detail.interviewers" :save="saveNote" :pending="createNote.isPending" />
        </div>
      </aside>
    </div>
  </div>
</template>
