import { MessageSquareTextIcon, NotebookPenIcon, PlusIcon } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

import type { CandidateNote, QAItem, SessionInterviewerView } from '@/api/types'
import { DeidText } from '@/components/common/deid'
import { EmptyState } from '@/components/common/states'
import { Badge, Textarea } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/form'
import { QUESTION_SOURCE_LABEL } from '@/lib/labels'
import { formatTime } from '@/lib/time'
import { cn } from '@/lib/utils'

export function QaLog({ qaItems, editedIds, answeringId }: { qaItems: QAItem[]; editedIds: Set<string>; answeringId: string | null }) {
  const endRef = useRef<HTMLLIElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'nearest' })
  }, [qaItems.length])
  if (qaItems.length === 0) {
    return <EmptyState compact icon={MessageSquareTextIcon} title="기록된 질문이 없습니다" description="사전 질문, AI 제안, 직접 입력 모두 여기에 순서대로 쌓입니다." />
  }
  return (
    <ol className="space-y-2" aria-label="Q&A 기록">
      <AnimatePresence initial={false}>
        {qaItems.map((q) => (
          <motion.li
            key={q.id}
            layout
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25 }}
            className="rounded-lg border bg-card p-3"
          >
            <div className="mb-1 flex items-center gap-1.5">
              <span className="font-mono text-[11px] font-semibold text-muted-foreground">Q{q.seq}</span>
              <Badge variant={q.question_source === 'ai_suggested' ? 'brand' : 'outline'} className="py-0 text-[10.5px]">
                {QUESTION_SOURCE_LABEL[q.question_source]}
              </Badge>
              {editedIds.has(q.id) && (
                <Badge variant="outline" className="py-0 text-[10.5px]">
                  수정함
                </Badge>
              )}
              {q.asked_at && <span className="ml-auto text-[11px] text-muted-foreground tabular">{formatTime(q.asked_at)}</span>}
            </div>
            <p className="text-[13px] leading-snug font-medium">{q.question}</p>
            {q.answer_deidentified ? (
              <p className="mt-1.5 line-clamp-3 text-[12.5px] leading-relaxed text-muted-foreground">
                <DeidText text={q.answer_deidentified} />
              </p>
            ) : (
              <p className={cn('mt-1.5 text-[12px] text-muted-foreground', answeringId === q.id && 'text-live')}>
                {answeringId === q.id ? '● 답변 중' : '답변 대기'}
              </p>
            )}
          </motion.li>
        ))}
      </AnimatePresence>
      <li ref={endRef} aria-hidden />
    </ol>
  )
}

export function NotesPanel({
  notes,
  panel,
  onAdd,
  pending,
}: {
  notes: CandidateNote[]
  panel: SessionInterviewerView[]
  onAdd: (content: string) => Promise<unknown>
  pending: boolean
}) {
  const [text, setText] = useState('')
  const names = new Map(panel.map((p) => [p.interviewer_id, p.interviewer.name]))
  const add = async () => {
    const t = text.trim()
    if (!t) return
    await onAdd(t)
    setText('')
  }
  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !e.nativeEvent.isComposing) {
              e.preventDefault()
              void add()
            }
          }}
          placeholder="관찰한 점을 기록하세요 (Ctrl+Enter). 메모는 작성자와 시각이 함께 저장됩니다."
          aria-label="면접관 메모"
          className="min-h-20 text-[13px]"
        />
        <div className="flex justify-end">
          <Button size="xs" variant="secondary" onClick={() => void add()} disabled={pending || !text.trim()}>
            <PlusIcon />
            메모 추가
          </Button>
        </div>
      </div>
      {notes.length === 0 ? (
        <EmptyState compact icon={NotebookPenIcon} title="메모가 없습니다" />
      ) : (
        <ol className="space-y-2">
          {[...notes].reverse().map((n) => (
            <li key={n.id} className="rounded-lg border bg-card p-3">
              <p className="text-[13px] leading-relaxed whitespace-pre-wrap">{n.content}</p>
              <p className="mt-1.5 text-[11px] text-muted-foreground">
                {names.get(n.author_id) ?? '면접관'} · {formatTime(n.created_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export function RecordTabs(props: {
  qaItems: QAItem[]
  editedIds: Set<string>
  answeringId: string | null
  notes: CandidateNote[]
  panel: SessionInterviewerView[]
  onAddNote: (content: string) => Promise<unknown>
  notePending: boolean
}) {
  return (
    <Tabs defaultValue="qa" className="flex min-h-0 flex-1 flex-col">
      <TabsList className="w-full">
        <TabsTrigger value="qa" className="flex-1">
          Q&A 기록 <span className="text-muted-foreground tabular">{props.qaItems.length}</span>
        </TabsTrigger>
        <TabsTrigger value="notes" className="flex-1">
          메모 <span className="text-muted-foreground tabular">{props.notes.length}</span>
        </TabsTrigger>
      </TabsList>
      <TabsContent value="qa" className="mt-3 min-h-0 flex-1">
        <QaLog qaItems={props.qaItems} editedIds={props.editedIds} answeringId={props.answeringId} />
      </TabsContent>
      <TabsContent value="notes" className="mt-3 min-h-0 flex-1">
        <NotesPanel notes={props.notes} panel={props.panel} onAdd={props.onAddNote} pending={props.notePending} />
      </TabsContent>
    </Tabs>
  )
}
