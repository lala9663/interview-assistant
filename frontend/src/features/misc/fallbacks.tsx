import { CompassIcon, TriangleAlertIcon } from 'lucide-react'
import { Link, useRouteError } from 'react-router'

import { Page } from '@/components/common/page'
import { EmptyState } from '@/components/common/states'
import { Skeleton } from '@/components/ui/basic'
import { Button } from '@/components/ui/button'

export function PageFallback() {
  return (
    <Page>
      <div className="mb-6 space-y-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-7 w-64" />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="mt-4 h-72" />
    </Page>
  )
}

export function NotFound() {
  return (
    <Page>
      <EmptyState
        icon={CompassIcon}
        title="페이지를 찾을 수 없습니다"
        description="주소가 바뀌었거나 삭제된 항목입니다."
        action={
          <Button asChild variant="outline" size="sm">
            <Link to="/">대시보드로</Link>
          </Button>
        }
      />
    </Page>
  )
}

export function RouteError() {
  const error = useRouteError()
  const message = error instanceof Error ? error.message : '예상하지 못한 오류가 발생했습니다.'
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <EmptyState
        icon={TriangleAlertIcon}
        title="화면을 그리지 못했습니다"
        description={message}
        action={
          <Button variant="outline" size="sm" onClick={() => window.location.assign('/')}>
            처음으로
          </Button>
        }
      />
    </div>
  )
}
