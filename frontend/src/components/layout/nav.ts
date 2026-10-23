import { BriefcaseBusinessIcon, CalendarDaysIcon, FileSearchIcon, LayoutDashboardIcon, MicIcon, type LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** FR ids the screen covers (shown in the command palette) */
  fr?: string
  keywords?: string
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '대시보드', icon: LayoutDashboardIcon, keywords: 'dashboard home 홈 현황' },
  { to: '/postings', label: '공고·역량 사전', icon: BriefcaseBusinessIcon, fr: 'FR-02', keywords: 'posting jd competency bars 역량' },
  { to: '/screening', label: '서류 선별', icon: FileSearchIcon, fr: 'FR-01·03', keywords: 'screening 지원자 candidate' },
  { to: '/sessions', label: '면접', icon: MicIcon, fr: 'FR-04~08', keywords: 'interview session live 평가 evaluation' },
  { to: '/schedule', label: '면접관 스케줄', icon: CalendarDaysIcon, fr: 'FR-09', keywords: 'schedule calendar 일정 가용' },
]
