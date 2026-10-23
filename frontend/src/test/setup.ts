import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'

import { resetDb } from '@/mocks/db'
import { mockConfig, resetLive } from '@/mocks/live'
import { server } from '@/mocks/node'

// jsdom gaps used by Radix, recharts and the transcript view.
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
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetLive()
  resetDb()
})
afterAll(() => server.close())
