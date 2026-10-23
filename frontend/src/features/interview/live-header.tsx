import { ArrowLeftIcon, CircleStopIcon, PanelLeftIcon, PenLineIcon } from 'lucide-react'
import { Link } from 'react-router'

import type { SessionDetail, StreamStatus } from '@/api/types'
import { Pseudonym } from '@/components/common/deid'
import { PanelAvatars } from '@/components/common/people'
import { ModeBadge } from '@/components/common/status'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
  Tooltip,
} from '@/components/ui/overlay'
import { formatElapsed } from '@/lib/time'
import { useNow } from '@/lib/use-now'
import { cn } from '@/lib/utils'

import type { Connection } from './use-transcript'

function Dot({ className }: { className?: string }) {
  return <span className={cn('size-2 shrink-0 rounded-full', className)} aria-hidden />
}

export function RecordingStatus({
  detail,
  status,
  connection,
}: {
  detail: SessionDetail
  status: StreamStatus | null
  connection: Connection
}) {
  const now = useNow(1000)
  const started = detail.session.started_at ? new Date(detail.session.started_at).getTime() : null
  const elapsed = started ? formatElapsed(now.getTime() - started) : '00:00'
  const manual = !detail.session.has_recording

  if (manual) {
    return (
      <div className="flex items-center gap-3 text-[12.5px] whitespace-nowrap">
        <span className="flex items-center gap-1.5 rounded-md bg-[color-mix(in_oklch,var(--warning)_12%,transparent)] px-2 py-1 font-medium text-warning">
          <PenLineIcon className="size-3.5" aria-hidden />
          수기 모드 · 녹음 안 함
        </span>
        <span className="font-mono font-semibold tabular" aria-label="경과 시간">
          {elapsed}
        </span>
      </div>
    )
  }

  const stt =
    connection === 'error' || status?.stt === 'down'
      ? { label: '전사 끊김', cls: 'bg-danger', hint: '녹음은 계속됩니다. 답변은 수기로 기록할 수 있습니다.' }
      : connection === 'reconnecting' || connection === 'connecting'
        ? { label: '전사 연결 중', cls: 'bg-warning animate-pulse', hint: '스트리밍 STT에 연결하는 중입니다.' }
        : status?.stt === 'degraded'
          ? { label: '전사 지연', cls: 'bg-warning', hint: '전사가 평소보다 늦습니다.' }
          : {
              label: '전사 정상',
              detail: status?.latency_ms ? `${(status.latency_ms / 1000).toFixed(1)}초` : null,
              cls: 'bg-success',
              hint: '부분 전사 지연 목표 0.5초 이하',
            }

  return (
    <div className="flex items-center gap-3 text-[12.5px] whitespace-nowrap">
      <span className="flex items-center gap-1.5 rounded-md bg-[color-mix(in_oklch,var(--live)_12%,transparent)] px-2 py-1 font-semibold text-live">
        <Dot className="animate-live bg-live" />
        REC
        <span className="font-mono tabular" aria-label="녹음 경과 시간">
          {elapsed}
        </span>
      </span>
      <Tooltip content={stt.hint}>
        <span tabIndex={0} className="flex items-center gap-1.5 text-muted-foreground outline-none">
          <Dot className={stt.cls} />
          <span className="tabular">
            {stt.label}
            {'detail' in stt && stt.detail && <span className="hidden xl:inline"> · {stt.detail}</span>}
          </span>
        </span>
      </Tooltip>
    </div>
  )
}

export function LiveHeader({
  detail,
  status,
  connection,
  onEnd,
  ending,
  onOpenCandidate,
}: {
  detail: SessionDetail
  status: StreamStatus | null
  connection: Connection
  onEnd: () => void
  ending: boolean
  onOpenCandidate: () => void
}) {
  const answered = detail.qa_items.filter((q) => q.answer_deidentified).length
  return (
    <div className="flex h-14 shrink-0 items-center gap-3 border-b bg-card/50 px-4">
      <Button asChild variant="ghost" size="icon-sm" aria-label="면접 목록으로">
        <Link to="/sessions">
          <ArrowLeftIcon />
        </Link>
      </Button>
      <Button variant="ghost" size="icon-sm" className="xl:hidden" onClick={onOpenCandidate} aria-label="지원자 정보와 사전 질문 열기">
        <PanelLeftIcon />
      </Button>
      <div className="flex min-w-0 items-center gap-2.5">
        <Pseudonym value={detail.card.candidate.pseudonym} className="whitespace-nowrap" />
        <span className="hidden truncate text-[13px] text-muted-foreground lg:block">{detail.posting.title}</span>
        <ModeBadge mode={detail.session.mode} />
        <PanelAvatars panel={detail.interviewers} className="hidden lg:flex" />
      </div>
      <div className="ml-auto flex items-center gap-4">
        <RecordingStatus detail={detail} status={status} connection={connection} />
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm" disabled={ending}>
              <CircleStopIcon />
              면접 종료
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>면접을 종료할까요?</AlertDialogTitle>
              <AlertDialogDescription>
                질문 {detail.qa_items.length}개(답변 {answered}개)가 기록되어 있습니다. 종료하면 녹음과 전사가 멈추고 AI 평점이 시작됩니다. AI
                평점은 참고용이며, 면접관 점수는 평가 화면에서 따로 입력합니다.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>계속 진행</AlertDialogCancel>
              <AlertDialogAction onClick={onEnd} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                종료하고 평가로
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  )
}
