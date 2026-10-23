import { createRouter, type RouterHistory, type RouteRecordRaw } from 'vue-router'

import AppShell from '@/components/layout/AppShell.vue'
import NotFound from '@/features/misc/NotFound.vue'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppShell,
    children: [
      { path: '', component: () => import('@/features/dashboard/DashboardPage.vue') },
      { path: 'postings', component: () => import('@/features/postings/PostingsPage.vue') },
      { path: 'postings/:postingId', component: () => import('@/features/postings/PostingDetailPage.vue') },
      { path: 'screening/:postingId?', component: () => import('@/features/screening/ScreeningPage.vue') },
      { path: 'sessions', component: () => import('@/features/sessions/SessionsPage.vue') },
      { path: 'sessions/:sessionId/live', component: () => import('@/features/interview/LiveInterviewPage.vue') },
      { path: 'sessions/:sessionId/evaluation', component: () => import('@/features/evaluation/EvaluationPage.vue') },
      { path: 'schedule', component: () => import('@/features/schedule/SchedulePage.vue') },
      { path: ':pathMatch(.*)*', component: NotFound },
    ],
  },
]

export function createAppRouter(history: RouterHistory) {
  return createRouter({
    history,
    routes,
    // New screen: start at the top. Same screen with a new query (?app=…) or back/forward: keep position.
    scrollBehavior: (to, from, saved) => saved ?? (to.path !== from.path ? { top: 0 } : false),
  })
}
