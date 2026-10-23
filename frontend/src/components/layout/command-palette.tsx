import { Command } from 'cmdk'
import { ArrowRightIcon, MicIcon, MonitorIcon, MoonIcon, SearchIcon, SunIcon, UserRoundIcon } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { useNavigate } from 'react-router'

import { useCandidateIndex, usePostings, useSessions } from '@/api/queries'
import { Kbd } from '@/components/ui/basic'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/overlay'
import { SCREENING_STATUS_LABEL, SESSION_STATUS_LABEL } from '@/lib/labels'
import { useTheme } from '@/lib/theme'
import { formatDateTime } from '@/lib/time'

import { NAV_ITEMS } from './nav'

function Item({ onSelect, children, value, keywords }: { onSelect: () => void; children: ReactNode; value: string; keywords?: string[] }) {
  return (
    <Command.Item
      value={value}
      keywords={keywords}
      onSelect={onSelect}
      className="group flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-sm outline-none select-none data-[selected=true]:bg-accent [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground"
    >
      {children}
    </Command.Item>
  )
}

/** Plain substring match: pseudonyms like CAND-0012 should not fuzzy-match CAND-0001. */
function substringFilter(value: string, search: string, keywords?: string[]) {
  const q = search.trim().toLowerCase()
  if (!q) return 1
  return `${value} ${(keywords ?? []).join(' ')}`.toLowerCase().includes(q) ? 1 : 0
}

const groupCls =
  '[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground'

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate()
  const { setPreference } = useTheme()
  const candidates = useCandidateIndex(open)
  const sessions = useSessions()
  const postings = usePostings()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        onOpenChange(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpenChange])

  const go = (to: string) => {
    onOpenChange(false)
    navigate(to)
  }

  const activeSessions = (sessions.data ?? []).filter((s) => s.status === 'in_progress' || s.status === 'scheduled' || s.status === 'completed')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent hideClose className="top-[14vh] max-w-xl translate-y-0 gap-0 overflow-hidden p-0 data-[state=open]:zoom-in-[0.98]">
        <DialogTitle className="sr-only">명령 팔레트</DialogTitle>
        <DialogDescription className="sr-only">화면, 지원자, 면접으로 이동합니다.</DialogDescription>
        <Command label="명령 팔레트" loop filter={substringFilter}>
          <div className="flex items-center gap-2 border-b px-3.5">
            <SearchIcon className="size-4 text-muted-foreground" aria-hidden />
            <Command.Input
              placeholder="화면, 지원자(CAND-…), 면접 검색"
              className="h-12 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <Kbd>Esc</Kbd>
          </div>
          <Command.List className="max-h-[min(440px,60vh)] scroll-py-2 overflow-y-auto p-1.5 scrollbar-thin">
            <Command.Empty className="py-10 text-center text-sm text-muted-foreground">결과가 없습니다.</Command.Empty>

            <Command.Group heading="이동" className={groupCls}>
              {NAV_ITEMS.map((n) => (
                <Item key={n.to} value={`nav ${n.label}`} keywords={[n.keywords ?? '', n.fr ?? '']} onSelect={() => go(n.to)}>
                  <n.icon />
                  <span className="flex-1">{n.label}</span>
                  {n.fr && <span className="text-[11px] text-muted-foreground">{n.fr}</span>}
                </Item>
              ))}
            </Command.Group>

            {activeSessions.length > 0 && (
              <Command.Group heading="면접" className={groupCls}>
                {activeSessions.slice(0, 8).map((s) => (
                  <Item
                    key={s.id}
                    value={`session ${s.candidate.pseudonym} ${s.posting.title} ${s.id}`}
                    keywords={[SESSION_STATUS_LABEL[s.status]]}
                    onSelect={() => go(s.status === 'completed' ? `/sessions/${s.id}/evaluation` : `/sessions/${s.id}/live`)}
                  >
                    <MicIcon />
                    <span className="font-mono text-[13px] font-semibold">{s.candidate.pseudonym}</span>
                    <span className="truncate text-muted-foreground">{s.posting.title}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                      {s.status === 'in_progress' ? (
                        <span className="font-medium text-live">진행 중</span>
                      ) : s.status === 'completed' ? (
                        '평가'
                      ) : (
                        s.scheduled_at && formatDateTime(s.scheduled_at)
                      )}
                    </span>
                  </Item>
                ))}
              </Command.Group>
            )}

            {(candidates.data?.length ?? 0) > 0 && (
              <Command.Group heading="지원자" className={groupCls}>
                {candidates.data!.map((c) => (
                  <Item
                    key={c.application_id}
                    value={`candidate ${c.pseudonym} ${c.posting_title}`}
                    onSelect={() => go(`/screening/${c.posting_id}?app=${c.application_id}`)}
                  >
                    <UserRoundIcon />
                    <span className="font-mono text-[13px] font-semibold">{c.pseudonym}</span>
                    <span className="truncate text-muted-foreground">{c.posting_title}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular">
                      {c.screening_status ? `${SCREENING_STATUS_LABEL[c.screening_status]} · ${c.fit_score}` : '선별 전'}
                    </span>
                  </Item>
                ))}
              </Command.Group>
            )}

            {(postings.data?.length ?? 0) > 0 && (
              <Command.Group heading="공고" className={groupCls}>
                {postings.data!.map((p) => (
                  <Item key={p.id} value={`posting ${p.title} ${p.job_family}`} onSelect={() => go(`/postings/${p.id}`)}>
                    <ArrowRightIcon />
                    <span className="truncate">{p.title}</span>
                    <span className="ml-auto text-xs text-muted-foreground">{p.job_family}</span>
                  </Item>
                ))}
              </Command.Group>
            )}

            <Command.Group heading="테마" className={groupCls}>
              <Item value="theme dark 다크" onSelect={() => (setPreference('dark'), onOpenChange(false))}>
                <MoonIcon />
                다크 모드
              </Item>
              <Item value="theme light 라이트" onSelect={() => (setPreference('light'), onOpenChange(false))}>
                <SunIcon />
                라이트 모드
              </Item>
              <Item value="theme system 시스템" onSelect={() => (setPreference('system'), onOpenChange(false))}>
                <MonitorIcon />
                시스템 설정 따르기
              </Item>
            </Command.Group>
          </Command.List>
          <div className="flex items-center gap-3 border-t px-3.5 py-2 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> 이동
            </span>
            <span className="flex items-center gap-1">
              <Kbd>↵</Kbd> 열기
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  )
}
