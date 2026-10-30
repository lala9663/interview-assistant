import {
  BriefcaseBusinessIcon,
  CalendarDaysIcon,
  ChartColumnIcon,
  FileSearchIcon,
  InboxIcon,
  LayoutDashboardIcon,
  LibraryBigIcon,
  MicIcon,
  SlidersHorizontalIcon,
} from '@lucide/vue'
import type { Component } from 'vue'

export interface NavItem {
  to: string
  label: string
  icon: Component
  /** extra search words for the command palette (requirement ids such as FR-02 included; never shown) */
  keywords?: string
  /** shown to admins only (the API answers 403 to everyone else anyway) */
  adminOnly?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '대시보드', icon: LayoutDashboardIcon, keywords: 'dashboard home 홈 현황' },
  { to: '/postings', label: '공고·역량 사전', icon: BriefcaseBusinessIcon, keywords: 'posting jd competency bars 역량 FR-02' },
  { to: '/screening', label: '서류 선별', icon: FileSearchIcon, keywords: 'screening 지원자 candidate FR-01 FR-03' },
  { to: '/sessions', label: '면접', icon: MicIcon, keywords: 'interview session live 평가 evaluation FR-04 FR-05 FR-06 FR-07 FR-08' },
  { to: '/schedule', label: '면접관 스케줄', icon: CalendarDaysIcon, keywords: 'schedule calendar 일정 가용 FR-09' },
  {
    to: '/question-bank',
    label: '질문 은행',
    icon: LibraryBigIcon,
    keywords: 'question bank 질문 은행 꼬리질문 평점 기준 예시 rubric 금지 질문 csv',
  },
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
  {
    to: '/admin/follow-up-metrics',
    label: '꼬리질문 지표',
    icon: ChartColumnIcon,
    keywords: 'metrics follow-up 꼬리질문 지표 채택률 질문 은행 중복 임베딩 색인',
    adminOnly: true,
  },
]

/** The menu a person sees: admin-only items need `is_admin`. */
export const navItemsFor = (isAdmin: boolean | undefined) => NAV_ITEMS.filter((n) => !n.adminOnly || isAdmin)
