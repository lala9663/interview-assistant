import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'

import { TooltipProvider } from '@/components/ui/overlay'
import { ThemeProvider } from '@/lib/theme'

/** Render a route element with the app's providers (fresh QueryClient, memory router). */
export function renderRoute(element: ReactNode, { path, url }: { path: string; url: string }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  const router = createMemoryRouter([{ path, element }], { initialEntries: [url] })
  return render(
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <TooltipProvider delayDuration={0}>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}

export function renderPlain(ui: ReactNode) {
  return render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>)
}
