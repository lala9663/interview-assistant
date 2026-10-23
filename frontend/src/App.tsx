import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { Toaster } from 'sonner'

import { AppShell } from '@/components/layout/app-shell'
import { TooltipProvider } from '@/components/ui/overlay'
import { RouteError, NotFound, PageFallback } from '@/features/misc/fallbacks'
import { createQueryClient } from '@/lib/query-client'
import { ThemeProvider, useTheme } from '@/lib/theme'

const DashboardPage = lazy(() => import('@/features/dashboard/dashboard-page'))
const PostingsPage = lazy(() => import('@/features/postings/postings-page'))
const PostingDetailPage = lazy(() => import('@/features/postings/posting-detail-page'))
const ScreeningPage = lazy(() => import('@/features/screening/screening-page'))
const SessionsPage = lazy(() => import('@/features/sessions/sessions-page'))
const LiveInterviewPage = lazy(() => import('@/features/interview/live-interview-page'))
const EvaluationPage = lazy(() => import('@/features/evaluation/evaluation-page'))
const SchedulePage = lazy(() => import('@/features/schedule/schedule-page'))

const page = (node: ReactNode) => <Suspense fallback={<PageFallback />}>{node}</Suspense>

const queryClient = createQueryClient()

const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: page(<DashboardPage />) },
      { path: 'postings', element: page(<PostingsPage />) },
      { path: 'postings/:postingId', element: page(<PostingDetailPage />) },
      { path: 'screening', element: page(<ScreeningPage />) },
      { path: 'screening/:postingId', element: page(<ScreeningPage />) },
      { path: 'sessions', element: page(<SessionsPage />) },
      { path: 'sessions/:sessionId/live', element: page(<LiveInterviewPage />) },
      { path: 'sessions/:sessionId/evaluation', element: page(<EvaluationPage />) },
      { path: 'schedule', element: page(<SchedulePage />) },
      { path: '*', element: <NotFound /> },
    ],
  },
])

function ThemedToaster() {
  const { resolved } = useTheme()
  return (
    <Toaster
      theme={resolved}
      position="bottom-right"
      toastOptions={{ classNames: { toast: 'font-sans !rounded-lg !border !shadow-xl', description: '!text-muted-foreground' } }}
    />
  )
}

export function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={250}>
          <RouterProvider router={router} />
          <ThemedToaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  )
}
