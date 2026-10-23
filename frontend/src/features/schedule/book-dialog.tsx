import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { useCreateSession, useSchedulable } from '@/api/queries'
import type { Interviewer, ScheduleSuggestion, SessionMode } from '@/api/types'
import { Label } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/form'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/overlay'
import { formatDate, formatTime } from '@/lib/time'

/** Turn a suggested slot into a scheduled session (확정 일정). */
export function BookDialog({
  slot,
  interviewers,
  onClose,
}: {
  slot: ScheduleSuggestion | null
  interviewers: Interviewer[]
  onClose: () => void
}) {
  const navigate = useNavigate()
  const apps = useSchedulable(slot !== null)
  const create = useCreateSession()
  const [appId, setAppId] = useState('')
  const [mode, setMode] = useState<SessionMode>('remote')
  const panel = slot ? interviewers.filter((i) => slot.interviewer_ids.includes(i.id)) : []
  const [lead, setLead] = useState('')
  const leadId = lead || panel[0]?.id || ''

  const submit = () => {
    if (!slot || !appId) return
    create.mutate(
      {
        application_id: appId,
        mode,
        scheduled_at: slot.start_at,
        interviewers: panel.map((i) => ({ interviewer_id: i.id, role: i.id === leadId ? 'lead' : 'panel' })),
      },
      {
        onSuccess: (s) => {
          toast.success(`${s.candidate.pseudonym} 면접을 잡았습니다`, {
            description: `${formatDate(slot.start_at)} ${formatTime(slot.start_at)}`,
            action: { label: '보기', onClick: () => navigate('/sessions') },
          })
          onClose()
        },
        onError: (e) => toast.error('일정을 잡지 못했습니다', { description: e instanceof ApiError ? e.message : undefined }),
      },
    )
  }

  return (
    <Dialog open={slot !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>면접 잡기</DialogTitle>
          <DialogDescription>
            {slot && `${formatDate(slot.start_at)} ${formatTime(slot.start_at)}–${formatTime(slot.end_at)} · 면접관 ${panel.map((p) => p.name).join(', ')}`}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>지원자</Label>
            <Select value={appId} onValueChange={setAppId}>
              <SelectTrigger aria-label="지원자 선택">
                <SelectValue placeholder={apps.isPending ? '불러오는 중…' : '서류 통과 지원자 선택'} />
              </SelectTrigger>
              <SelectContent>
                {apps.data?.map((a) => (
                  <SelectItem key={a.application_id} value={a.application_id}>
                    {a.candidate.pseudonym} · {a.posting.title} · 적합도 {a.fit_score}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {apps.data?.length === 0 && <p className="text-xs text-muted-foreground">면접을 잡을 수 있는 서류 통과 지원자가 없습니다.</p>}
          </div>
          <div className="flex flex-wrap gap-6">
            <div className="space-y-1.5">
              <Label>방식</Label>
              <Segmented type="single" value={mode} onValueChange={(v) => v && setMode(v as SessionMode)} aria-label="면접 방식">
                <SegmentedItem value="remote">비대면</SegmentedItem>
                <SegmentedItem value="onsite">대면</SegmentedItem>
              </Segmented>
            </div>
            <div className="min-w-48 flex-1 space-y-1.5">
              <Label>주관 면접관</Label>
              <Select value={leadId} onValueChange={setLead}>
                <SelectTrigger aria-label="주관 면접관">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {panel.map((i) => (
                    <SelectItem key={i.id} value={i.id}>
                      {i.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button onClick={submit} disabled={!appId || create.isPending}>
            {create.isPending ? '잡는 중…' : '일정 확정'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
