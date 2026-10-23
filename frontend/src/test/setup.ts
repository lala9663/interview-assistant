import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/vue'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { resetDb } from '@/mocks/db'
import { mockConfig, resetLive } from '@/mocks/live'
import { server } from '@/mocks/node'

// jsdom gaps used by Reka UI, Chart.js and the transcript view.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
Element.prototype.scrollIntoView ??= vi.fn()
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.releasePointerCapture ??= () => {}

// Mock API timings collapse to ~0 so streaming tests run fast.
mockConfig.speed = 0.001

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(async () => {
  cleanup()
  // Let the mock engine's scaled-down timers settle first (a recorded question starts its scripted answer
  // ~1ms later); otherwise that answer starts after resetLive() and occupies the next test's session.
  await new Promise((r) => setTimeout(r, 20))
  server.resetHandlers()
  resetLive()
  resetDb()
})
afterAll(() => server.close())
