<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import { qk, useAnswerQA, useCreateNote, useCreateQA, useSessionLifecycle } from '@/api/queries'
import type { CreateQARequest, PresetQuestion, QAItem, SessionDetail } from '@/api/types'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { errorMessage } from '@/lib/toast'

import CandidateSummary from './CandidateSummary.vue'
import ConnectionBanner from './ConnectionBanner.vue'
import FollowUpPanel from './FollowUpPanel.vue'
import { useFollowUps, type Suggestion } from './follow-ups'
import LiveHeader from './LiveHeader.vue'
import ManualAnswerBox from './ManualAnswerBox.vue'
import ManualLog from './ManualLog.vue'
import PresetQuestions from './PresetQuestions.vue'
import QuestionComposer from './QuestionComposer.vue'
import RecordTabs from './RecordTabs.vue'
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
const { end } = useSessionLifecycle(sessionId)
const editedIds = ref<ReadonlySet<string>>(new Set())
const pendingPreset = ref<string | null>(null)
const pendingSuggestion = ref<string | null>(null)
const sheetOpen = ref(false)

const qaItems = computed(() => props.detail.qa_items)
const latest = computed(() => qaItems.value[qaItems.value.length - 1])

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
const sttDown = computed(() => !manual && transcript.value.connection === 'error')
const listening = computed(() => !manual && !sttDown.value && answeringId.value !== null)

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
  sheetOpen.value = false
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
        toast.success(`Q${qa.seq}로 기록했습니다`, { description: edited ? 'AI 제안을 수정해 사용했습니다.' : 'AI 제안을 그대로 사용했습니다.' })
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
</script>

<template>
  <div class="flex flex-col md:h-[calc(100vh-3.5rem)]">
    <LiveHeader
      :detail="detail"
      :status="transcript.status"
      :connection="manual ? 'idle' : transcript.connection"
      :ending="end.isPending"
      @end="onEnd"
      @open-candidate="sheetOpen = true"
    />
    <div class="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[300px_minmax(0,1fr)_380px]">
      <aside class="hidden min-h-0 overflow-y-auto border-r p-4 scrollbar-thin xl:block" aria-label="지원자와 사전 질문">
        <div class="space-y-5">
          <CandidateSummary :card="detail.card" />
          <Separator />
          <PresetQuestions
            :presets="detail.preset_questions"
            :qa-items="qaItems"
            :disabled="createQA.isPending"
            :pending-id="pendingPreset"
            @ask="askPreset"
          />
        </div>
      </aside>

      <section class="flex h-[65vh] min-h-0 flex-col md:h-auto" aria-label="트랜스크립트">
        <ConnectionBanner v-if="!manual" :connection="transcript.connection" @reconnect="reconnect" />
        <ManualLog v-if="manual" :qa-items="qaItems" />
        <TranscriptView v-else :segments="transcript.segments" :partial="transcript.partial" :qa-items="qaItems" :listening="listening" />
        <ManualAnswerBox
          v-if="(manual || sttDown) && latest && !latest.answer_deidentified"
          :key="latest.id"
          :qa="latest"
          :pending="answerQA.isPending"
          @save="(a) => latest && saveManualAnswer(latest, a)"
        />
        <QuestionComposer :disabled="false" :pending="createQA.isPending" @submit="(text) => ask({ question: text, question_source: 'interviewer' })" />
      </section>

      <aside class="flex min-h-0 flex-col gap-5 overflow-y-auto border-l p-4 scrollbar-thin" aria-label="꼬리질문과 기록">
        <FollowUpPanel
          :state="followUps"
          :listening="listening"
          :has-answer="Boolean(followUps.qaItemId)"
          :disabled="createQA.isPending"
          :pending-suggestion-id="pendingSuggestion"
          @use="applySuggestion"
          @retry="retryFollowUps"
        />
        <Separator />
        <RecordTabs
          :qa-items="qaItems"
          :edited-ids="editedIds"
          :answering-id="listening ? answeringId : null"
          :notes="detail.notes"
          :panel="detail.interviewers"
          :save-note="saveNote"
          :note-pending="createNote.isPending"
        />
      </aside>
    </div>

    <Sheet v-model:open="sheetOpen">
      <SheetContent side="left" class="max-w-[360px] overflow-y-auto p-5">
        <SheetTitle class="sr-only">지원자와 사전 질문</SheetTitle>
        <SheetDescription class="sr-only">지원자 요약과 사전 질문 목록</SheetDescription>
        <div class="space-y-5">
          <CandidateSummary :card="detail.card" />
          <Separator />
          <PresetQuestions
            :presets="detail.preset_questions"
            :qa-items="qaItems"
            :disabled="createQA.isPending"
            :pending-id="pendingPreset"
            @ask="askPreset"
          />
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>
