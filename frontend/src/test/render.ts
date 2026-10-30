import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { render } from '@testing-library/vue'
import { defineComponent, h, type Component } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

import { TooltipProvider } from '@/components/ui/tooltip'

/** Real <Transition>/<TransitionGroup> (test-utils stubs them, which would drop the <ol> a TransitionGroup renders). */
const stubs = { transition: false, 'transition-group': false }

/**
 * Render a route component with the app's providers (fresh QueryClient, memory router). `shell` (the app's
 * AppShell) wraps the route the way the app does, with its menu and top bar.
 */
export async function renderRoute(
  component: Component,
  { path, url, props = {}, shell }: { path: string; url: string; props?: Record<string, unknown>; shell?: Component },
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  // Links to other screens (e.g. "면접 목록으로") resolve to an empty page instead of a router warning.
  const elsewhere = { render: () => null }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: shell
      ? [{ path: '/', component: shell, children: [{ path: path.slice(1), component, props: () => props }, { path: ':other(.*)*', component: elsewhere }] }]
      : [
          { path, component, props: () => props },
          { path: '/:other(.*)*', component: elsewhere },
        ],
  })
  await router.push(url)
  await router.isReady()
  const Host = defineComponent(() => () => h(TooltipProvider, { delayDuration: 0 }, () => h(RouterView)))
  return render(Host, { global: { stubs, plugins: [router, [VueQueryPlugin, { queryClient: client }]] } })
}

/** Render a presentational component (no router or queries) inside the tooltip provider. */
export function renderPlain(component: Component, props: Record<string, unknown> = {}) {
  const Host = defineComponent(() => () => h(TooltipProvider, { delayDuration: 0 }, () => h(component, props)))
  return render(Host, { global: { stubs } })
}
