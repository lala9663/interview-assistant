import { BriefcaseBusinessIcon, CalendarDaysIcon, FileSearchIcon, InboxIcon, LayoutDashboardIcon, MicIcon, SlidersHorizontalIcon } from '@lucide/vue'
import type { Component } from 'vue'

export interface NavItem {
  to: string
  label: string
  icon: Component
  /** FR ids the screen covers (shown in the command palette) */
  fr?: string
  keywords?: string
  /** shown to admins only (the API answers 403 to everyone else anyway) */
  adminOnly?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '대시보드', icon: LayoutDashboardIcon, keywords: 'dashboard home 홈 현황' },
  { to: '/postings', label: '공고·역량 사전', icon: BriefcaseBusinessIcon, fr: 'FR-02', keywords: 'posting jd competency bars 역량' },
  { to: '/screening', label: '서류 선별', icon: FileSearchIcon, fr: 'FR-01·03', keywords: 'screening 지원자 candidate' },
  { to: '/sessions', label: '면접', icon: MicIcon, fr: 'FR-04~08', keywords: 'interview session live 평가 evaluation' },
  { to: '/schedule', label: '면접관 스케줄', icon: CalendarDaysIcon, fr: 'FR-09', keywords: 'schedule calendar 일정 가용' },
  {
    to: '/admin/models',
    label: '모델 설정',
    icon: SlidersHorizontalIcon,
    keywords: 'admin model llm stt whisper 관리자 모델 전사 임베딩 화자분리',
    adminOnly: true,
  },
  {
    to: '/admin/intake',
    label: '연동 현황',
    icon: InboxIcon,
    keywords: 'intake site recruiting 채용 사이트 연동 수신 지원서 이벤트 실패 다시 처리',
    adminOnly: true,
  },
]

/** The menu a person sees: admin-only items need `is_admin`. */
export const navItemsFor = (isAdmin: boolean | undefined) => NAV_ITEMS.filter((n) => !n.adminOnly || isAdmin)
