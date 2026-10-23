import { useQueryClient } from '@tanstack/react-query'
import { CalendarXIcon, CircleCheckBigIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { qk, useAnswerQA, useCreateNote, useCreateQA, useSession, useSessionLifecycle } from '@/api/queries'
import type { CreateQARequest, PresetQuestion, QAItem, SessionDetail } from '@/api/types'
import { Page } from '@/components/common/page'
import { EmptyState, ErrorState } from '@/components/common/states'
import { Separator, Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/overlay'

import { CandidateSummary, PresetQuestions } from './candidate-panel'
import { FollowUpPanel } from './follow-up-panel'
import { useFollowUps, type Suggestion } from './follow-ups'
import { LiveHeader } from './live-header'
import { PreStart } from './pre-start'
import { RecordTabs } from './record-tabs'
import { ConnectionBanner, ManualAnswerBox, ManualLog, QuestionComposer, TranscriptView } from './transcript-panel'
import { useTranscript } from './use-transcript'

const errorMessage = (e: unknown) => (e instanceof ApiError ? e.message : '요청이 실패했습니다.')

function LiveSkeleton() {
  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="flex h-14 items-center gap-3 border-b px-4">
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="ml-auto h-8 w-40" />
      </div>
      <div className="grid flex-1 grid-cols-[300px_1fr_380px] gap-0">
        <div className="space-y-3 border-r p-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
        </div>
        <div className="space-y-3 p-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
        <div className="space-y-3 border-l p-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      </div>
    </div>
  )
}

function LiveRoom({ detail }: { detail: SessionDetail }) {
  const sessionId = detail.session.id
  const navigate = useNavigate()
  const qc = useQueryClient()
  const manual = !detail.session.has_recording
  const { state: followUps, request: requestFollowUps, markUsed } = useFollowUps(sessionId)
  const createQA = useCreateQA(sessionId)
  const answerQA = useAnswerQA(sessionId)
  const createNote = useCreateNote(sessionId)
  const { end } = useSessionLifecycle(sessionId)
  const [editedIds, setEditedIds] = useState<Set<string>>(new Set())
  const [pendingPreset, setPendingPreset] = useState<string | null>(null)
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  const qaItems = detail.qa_items
  const latest = qaItems[qaItems.length - 1]
  const latestRef = useRef(latest)
  useEffect(() => {
    latestRef.current = latest
  }, [latest])

  const onAnswered = useCallback(
    (e: { qa_item_id: string }) => {
      if (latestRef.current?.id === e.qa_item_id) void requestFollowUps(e.qa_item_id)
    },
    [requestFollowUps],
  )
  const transcript = useTranscript(sessionId, !manual, onAnswered)

  // Reopened page after an answer finished: offer follow-ups for it right away.
  const autoRequested = useRef(false)
  useEffect(() => {
    if (autoRequested.current || followUps.status !== 'idle' || !latest?.answer_deidentified) return
    autoRequested.current = true
    void requestFollowUps(latest.id)
  }, [latest, followUps.status, requestFollowUps])

  const answeringId = latest && !latest.answer_deidentified ? latest.id : null
  const sttDown = !manual && transcript.connection === 'error'
  const listening = !manual && !sttDown && answeringId !== null

  const appendQA = (qa: QAItem) =>
    qc.setQueryData<SessionDetail>(qk.session(sessionId), (d) => (d && !d.qa_items.some((x) => x.id === qa.id) ? { ...d, qa_items: [...d.qa_items, qa] } : d))

  const ask = (body: CreateQARequest, opts: { onDone?: (qa: QAItem) => void; finally?: () => void } = {}) =>
    createQA.mutate(body, {
      onSuccess: (qa) => {
        appendQA(qa)
        opts.onDone?.(qa)
      },
      onError: (e) => toast.error('질문을 기록하지 못했습니다', { description: errorMessage(e) }),
      onSettled: opts.finally,
    })

  const askPreset = (p: PresetQuestion) => {
    setPendingPreset(p.id)
    ask({ question: p.question, question_source: 'preset', preset_question_id: p.id }, { finally: () => setPendingPreset(null) })
  }

  const applySuggestion = (s: Suggestion, text: string, edited: boolean) => {
    if (!followUps.batchId) return
    setPendingSuggestion(s.id)
    ask(
      {
        question: text,
        question_source: 'ai_suggested',
        suggestion: { batch_id: followUps.batchId, suggestion_id: s.id, edited, original_question: s.text },
      },
      {
        onDone: (qa) => {
          markUsed(s.id, qa.seq, edited)
          if (edited) setEditedIds((prev) => new Set(prev).add(qa.id))
          toast.success(`Q${qa.seq}로 기록했습니다`, { description: edited ? 'AI 제안을 수정해 사용했습니다.' : 'AI 제안을 그대로 사용했습니다.' })
        },
        finally: () => setPendingSuggestion(null),
      },
    )
  }

  const saveManualAnswer = (qa: QAItem, answer: string) =>
    answerQA.mutate(
      { qaId: qa.id, answer },
      {
        onSuccess: (updated) => {
          qc.setQueryData<SessionDetail>(qk.session(sessionId), (d) => (d ? { ...d, qa_items: d.qa_items.map((x) => (x.id === updated.id ? updated : x)) } : d))
          void requestFollowUps(updated.id)
        },
        onError: (e) => toast.error('답변을 저장하지 못했습니다', { description: errorMessage(e) }),
      },
    )

  const onEnd = () =>
    end.mutate(undefined, {
      onSuccess: () => {
        toast.success('면접을 종료했습니다', { description: 'AI 채점을 시작했습니다. 면접관 점수를 입력하세요.' })
        navigate(`/sessions/${sessionId}/evaluation`)
      },
      onError: (e) => toast.error('면접을 종료하지 못했습니다', { description: errorMessage(e) }),
    })

  const leftPanel = (
    <div className="space-y-5">
      <CandidateSummary card={detail.card} />
      <Separator />
      <PresetQuestions
        presets={detail.preset_questions}
        qaItems={qaItems}
        disabled={createQA.isPending}
        pendingId={pendingPreset}
        onAsk={(p) => {
          askPreset(p)
          setSheetOpen(false)
        }}
      />
    </div>
  )

  return (
    <div className="flex flex-col md:h-[calc(100vh-3.5rem)]">
      <LiveHeader
        detail={detail}
        status={transcript.status}
        connection={manual ? 'idle' : transcript.connection}
        onEnd={onEnd}
        ending={end.isPending}
        onOpenCandidate={() => setSheetOpen(true)}
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[300px_minmax(0,1fr)_380px]">
        <aside className="hidden min-h-0 overflow-y-auto border-r p-4 scrollbar-thin xl:block" aria-label="지원자와 사전 질문">
          {leftPanel}
        </aside>

        <section className="flex h-[65vh] min-h-0 flex-col md:h-auto" aria-label="트랜스크립트">
          {!manual && <ConnectionBanner connection={transcript.connection} onReconnect={transcript.reconnect} />}
          {manual ? (
            <ManualLog qaItems={qaItems} />
          ) : (
            <TranscriptView segments={transcript.segments} partial={transcript.partial} qaItems={qaItems} listening={listening} />
          )}
          {(manual || sttDown) && latest && !latest.answer_deidentified && (
            <ManualAnswerBox key={latest.id} qa={latest} onSave={(a) => saveManualAnswer(latest, a)} pending={answerQA.isPending} />
          )}
          <QuestionComposer
            onSubmit={(text) => ask({ question: text, question_source: 'interviewer' })}
            disabled={false}
            pending={createQA.isPending}
          />
        </section>

        <aside className="flex min-h-0 flex-col gap-5 overflow-y-auto border-l p-4 scrollbar-thin" aria-label="꼬리질문과 기록">
          <FollowUpPanel
            state={followUps}
            listening={listening}
            hasAnswer={Boolean(followUps.qaItemId)}
            disabled={createQA.isPending}
            pendingSuggestionId={pendingSuggestion}
            onUse={applySuggestion}
            onRetry={() => followUps.qaItemId && void requestFollowUps(followUps.qaItemId)}
          />
          <Separator />
          <RecordTabs
            qaItems={qaItems}
            editedIds={editedIds}
            answeringId={listening ? answeringId : null}
            notes={detail.notes}
            panel={detail.interviewers}
            onAddNote={(c) => createNote.mutateAsync(c).catch((e) => toast.error('메모를 저장하지 못했습니다', { description: errorMessage(e) }))}
            notePending={createNote.isPending}
          />
        </aside>
      </div>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left" className="max-w-[360px] overflow-y-auto p-5">
          <SheetTitle className="sr-only">지원자와 사전 질문</SheetTitle>
          <SheetDescription className="sr-only">지원자 요약과 사전 질문 목록</SheetDescription>
          {leftPanel}
        </SheetContent>
      </Sheet>
    </div>
  )
}

export default function LiveInterviewPage() {
  const { sessionId = '' } = useParams()
  const session = useSession(sessionId)
  const qc = useQueryClient()

  if (session.isPending) return <LiveSkeleton />
  if (session.isError) {
    return (
      <Page>
        <ErrorState error={session.error} onRetry={() => void session.refetch()} />
      </Page>
    )
  }
  const detail = session.data
  switch (detail.session.status) {
    case 'scheduled':
      return <PreStart detail={detail} onStarted={() => void qc.invalidateQueries({ queryKey: qk.session(sessionId) })} />
    case 'in_progress':
      return <LiveRoom key={detail.session.id} detail={detail} />
    case 'completed':
      return (
        <Page>
          <EmptyState
            icon={CircleCheckBigIcon}
            title="종료된 면접입니다"
            description="Q&A와 AI 참고 점수, 면접관 점수는 평가 화면에서 확인합니다."
            action={
              <div className="flex gap-2">
                <Button asChild>
                  <Link to={`/sessions/${sessionId}/evaluation`}>평가 보기</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/sessions">면접 목록</Link>
                </Button>
              </div>
            }
          />
        </Page>
      )
    case 'cancelled':
      return (
        <Page>
          <EmptyState icon={CalendarXIcon} title="취소된 면접입니다" action={<Button asChild variant="outline"><Link to="/sessions">면접 목록</Link></Button>} />
        </Page>
      )
  }
}
