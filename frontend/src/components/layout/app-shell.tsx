import { FlaskConicalIcon, SearchIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'

import { useMe, useSessions } from '@/api/queries'
import { Kbd } from '@/components/ui/basic'
import { Tooltip } from '@/components/ui/overlay'
import { cn } from '@/lib/utils'

import { CommandPalette } from './command-palette'
import { NAV_ITEMS } from './nav'
import { ThemeToggle } from './theme-toggle'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'
const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" aria-hidden>
          <path d="M5 8a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-4l-4 3v-3a3 3 0 0 1-3-3z" />
        </svg>
      </span>
      <span className="hidden text-[14px] leading-tight font-semibold tracking-tight lg:block">
        면접 어시스턴트
        <span className="block text-[11px] font-normal text-muted-foreground">Interview Assistant</span>
      </span>
    </Link>
  )
}

function LiveSessionPill() {
  const live = useSessions('in_progress')
  const session = live.data?.[0]
  const { pathname } = useLocation()
  if (!session || pathname.endsWith(`${session.id}/live`)) return null
  return (
    <Tooltip content="진행 중인 면접으로 돌아가기" side="right">
      <Link
        to={`/sessions/${session.id}/live`}
        className="mx-2 mb-2 flex items-center gap-2 rounded-lg border border-[color-mix(in_oklch,var(--live)_35%,transparent)] bg-[color-mix(in_oklch,var(--live)_9%,transparent)] px-2.5 py-2 text-xs transition-colors hover:bg-[color-mix(in_oklch,var(--live)_14%,transparent)]"
      >
        <span className="size-2 shrink-0 animate-live rounded-full bg-live" aria-hidden />
        <span className="hidden min-w-0 lg:block">
          <span className="block font-medium text-live">진행 중 면접</span>
          <span className="block truncate font-mono text-muted-foreground">{session.candidate.pseudonym}</span>
        </span>
      </Link>
    </Tooltip>
  )
}

function Sidebar() {
  const me = useMe()
  return (
    <aside className="sticky top-0 flex h-screen w-14 shrink-0 flex-col border-r bg-sidebar lg:w-60">
      <div className="flex h-14 items-center px-3.5 lg:px-4">
        <Logo />
      </div>
      <nav className="flex flex-1 flex-col gap-0.5 px-2 pt-2" aria-label="주요 메뉴">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] font-medium text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50',
                isActive && 'bg-accent text-foreground',
              )
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className={cn('size-[17px] shrink-0', isActive && 'text-brand')} aria-hidden />
                <span className="hidden truncate lg:block">{item.label}</span>
                {item.fr && <span className="ml-auto hidden text-[10.5px] font-normal text-muted-foreground/70 lg:block">{item.fr}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <LiveSessionPill />
      <div className="border-t p-2">
        {USE_MOCKS && (
          <Tooltip content="백엔드 없이 모의 API(MSW)로 동작 중입니다. 데이터는 새로고침하면 초기화됩니다." side="right">
            <div className="mb-1 flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs text-muted-foreground">
              <FlaskConicalIcon className="size-3.5 shrink-0" aria-hidden />
              <span className="hidden lg:block">모의 API 모드</span>
            </div>
          </Tooltip>
        )}
        <div className="flex items-center gap-2.5 rounded-md px-2 py-1.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
            {me.data?.name.slice(0, 1) ?? ''}
          </span>
          <span className="hidden min-w-0 lg:block">
            <span className="block truncate text-[13px] font-medium">{me.data?.name ?? '…'}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{me.data?.department ?? ''}</span>
          </span>
        </div>
      </div>
    </aside>
  )
}

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-md lg:px-6">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="flex h-8 w-full max-w-80 items-center gap-2 rounded-md border bg-card px-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <SearchIcon className="size-3.5" aria-hidden />
            <span className="flex-1 text-left">검색 또는 이동…</span>
            <Kbd>{IS_MAC ? '⌘K' : 'Ctrl K'}</Kbd>
          </button>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  )
}
