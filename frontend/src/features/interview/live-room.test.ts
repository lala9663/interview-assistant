import { screen, waitFor, within } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AppShell from '@/components/layout/AppShell.vue'
import { MINUTE } from '@/lib/time'
import { getDb } from '@/mocks/db'
import { renderRoute } from '@/test/render'

import LiveInterviewPage from './LiveInterviewPage.vue'

const LIVE = '0a1b2c3d-0000-4000-9000-live00000000' // CAND-0007 1차, Q1-Q3 asked, Q3's answer streams in
const URL = `/sessions/${LIVE}/live`
const WAIT = { timeout: 15_000, interval: 100 }

const open = (shell?: typeof AppShell) => renderRoute(LiveInterviewPage, { path: '/sessions/:sessionId/live', url: URL, shell })

/** Every offered card usable (finished and past its duplicate check), watched with a plain selector (see live-interview.test.ts). */
async function cardsReady() {
  let panel: HTMLElement | null = null
  await waitFor(() => expect((panel = document.querySelector<HTMLElement>('section[aria-label="꼬리질문 제안"]'))).not.toBeNull(), WAIT)
  const ready = () => [...panel!.querySelectorAll<HTMLButtonElement>('[data-testid="use-suggestion"]')].filter((b) => !b.disabled)
  await waitFor(() => expect(ready().length).toBeGreaterThanOrEqual(4), { ...WAIT, timeout: 40_000, container: panel! })
}
const card = (n: number) => document.querySelector<HTMLElement>(`li[aria-label^="꼬리질문 후보 ${n} ("]`)!
const cardText = (n: number) => within(card(n)).getByTestId('suggestion-text').textContent!.trim()
const asked = () => getDb().qaOf(LIVE)

/** The room measures its own width with a ResizeObserver; jsdom has no layout, so report one. */
function roomWidth(width: number) {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      cb: ResizeObserverCallback
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb
      }
      observe(el: Element) {
        if (el.getAttribute('data-testid') === 'live-room') this.cb([{ contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver)
      }
      unobserve() {}
      disconnect() {}
    },
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('live room: keyboard', { timeout: 60_000 }, () => {
  it('asks the card with the number pressed, shows the keys, and leaves typing and Alt+number alone', async () => {
    const user = userEvent.setup()
    await open()
    await cardsReady()
    expect(screen.getByTestId('suggestion-keys')).toHaveTextContent('바로 사용')
    const use3 = within(card(3)).getByRole('button', { name: '이 질문 사용' })
    expect(use3).toHaveAttribute('aria-keyshortcuts', '3')

    // Typing in the composer: the digit is text. Alt+1 is the microphone's (질문 중), not a card.
    const composer = screen.getByRole('textbox', { name: '직접 질문 입력' })
    await user.click(composer)
    expect(screen.getByTestId('suggestion-keys')).toHaveTextContent('입력 중에는 숫자 키가 쉽니다')
    await user.keyboard('3')
    expect(composer).toHaveValue('3')
    await user.keyboard('{Escape}')
    expect(composer).not.toHaveFocus()
    await user.keyboard('{Alt>}1{/Alt}')
    expect(asked()).toHaveLength(3)

    const question = cardText(3)
    await user.keyboard('3')
    await waitFor(() => expect(asked()).toHaveLength(4), WAIT)
    expect(asked()[3]).toMatchObject({ seq: 4, question_source: 'ai_suggested', question })
    expect(await within(card(3)).findByText(/기록됨 · Q4/, {}, WAIT)).toBeInTheDocument()

    // One pick per answer: the other numbers do nothing now.
    await user.keyboard('1')
    await new Promise((r) => setTimeout(r, 50))
    expect(asked()).toHaveLength(4)
  })

  it('Shift+number opens the card for editing first; Esc cancels, Enter asks the edited question', async () => {
    const user = userEvent.setup()
    await open()
    await cardsReady()
    await user.keyboard('{Shift>}2{/Shift}')
    expect(within(card(2)).getByRole('textbox', { name: '꼬리질문 수정' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(within(card(2)).queryByRole('textbox', { name: '꼬리질문 수정' })).toBeNull()

    await user.keyboard('{Shift>}2{/Shift}')
    const box = within(card(2)).getByRole('textbox', { name: '꼬리질문 수정' })
    await user.clear(box)
    await user.type(box, '그 기준을 팀에 어떻게 공유했나요?{Enter}')
    await waitFor(() => expect(asked()).toHaveLength(4), WAIT)
    expect(asked()[3]).toMatchObject({ question: '그 기준을 팀에 어떻게 공유했나요?', question_source: 'ai_suggested' })
  })

  it('"/" jumps to the composer', async () => {
    const user = userEvent.setup()
    await open()
    await screen.findByRole('textbox', { name: '직접 질문 입력' })
    await user.keyboard('/')
    expect(screen.getByRole('textbox', { name: '직접 질문 입력' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: '직접 질문 입력' })).toHaveValue('')
  })
})

describe('live room: narrower windows', { timeout: 60_000 }, () => {
  it('a 1024 px room keeps 사전 질문 and 지원자 one tab away, and a number key brings the cards back instead of asking', async () => {
    roomWidth(1024)
    const user = userEvent.setup()
    await open()
    const tabs = await screen.findByRole('tablist', { name: '다음 질문과 지원자' })
    expect(screen.queryByRole('complementary', { name: '지원자와 사전 질문' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^사전 질문 기록/ })).toBeNull()

    await user.click(within(tabs).getByRole('tab', { name: /사전 질문/ }))
    await cardsReady()
    expect(screen.getByTestId('fresh-follow-ups')).toBeInTheDocument() // new cards wait on the other tab
    await user.keyboard('1')
    expect(within(tabs).getByRole('tab', { name: /꼬리질문/ })).toHaveAttribute('aria-selected', 'true')
    expect(asked()).toHaveLength(3)

    await user.click(within(tabs).getByRole('tab', { name: /사전 질문/ }))
    const preset = screen.getAllByRole('button', { name: /^사전 질문 기록/ })[0]!
    await user.click(preset)
    await waitFor(() => expect(asked()).toHaveLength(4), WAIT)
    expect(asked()[3]!.question_source).toBe('preset')

    await user.click(within(tabs).getByRole('tab', { name: '지원자' }))
    expect(screen.getByRole('region', { name: '지원자 요약' })).toBeVisible()
  })

  it('a wide room keeps them in their own column, 사전 질문 first and 지원자 one tab away', async () => {
    roomWidth(1366)
    const user = userEvent.setup()
    await open()
    const side = await screen.findByRole('complementary', { name: '지원자와 사전 질문' })
    expect(screen.queryByRole('tablist', { name: '다음 질문과 지원자' })).toBeNull()
    expect(within(side).getAllByRole('button', { name: /^사전 질문 기록/ }).length).toBeGreaterThan(0)
    expect(within(side).queryByRole('region', { name: '지원자 요약' })).toBeNull()
    await user.click(within(side).getByRole('tab', { name: '지원자' }))
    expect(within(side).getByRole('region', { name: '지원자 요약' })).toBeVisible()
  })
})

describe('live room: interview mode and time', { timeout: 60_000 }, () => {
  it('folds the app menu away while the interview runs, brings it back on request, and restores it on leaving', async () => {
    const user = userEvent.setup()
    await open(AppShell)
    await screen.findByTestId('menu-toggle')
    expect(screen.queryByRole('navigation', { name: '주요 메뉴' })).toBeNull()

    await user.click(screen.getByRole('button', { name: '메뉴 펼치기' }))
    expect(screen.getByRole('navigation', { name: '주요 메뉴' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '메뉴 접기' }))
    expect(screen.queryByRole('navigation', { name: '주요 메뉴' })).toBeNull()

    await user.click(screen.getByRole('link', { name: '면접 목록으로' }))
    expect(await screen.findByRole('navigation', { name: '주요 메뉴' })).toBeInTheDocument()
  })

  it('shows elapsed against the planned hour', async () => {
    await open()
    const clock = await screen.findByTestId('session-clock')
    expect(clock).toHaveTextContent(/60분 중 1[2-4]분/)
    expect(clock).toHaveAttribute('data-phase', 'on_time')
    expect(screen.queryByTestId('long-open-banner')).toBeNull()
  })

  it('asks to end a session left open far past its plan, and can be put off for an hour', async () => {
    getDb().session(LIVE)!.started_at = new Date(Date.now() - (37 * 60 + 46) * MINUTE).toISOString()
    const user = userEvent.setup()
    await open()
    const banner = await screen.findByTestId('long-open-banner')
    expect(banner).toHaveTextContent('37시간 46분째 열려 있는 면접입니다')
    expect(screen.getByTestId('session-clock')).toHaveAttribute('data-phase', 'long_open')

    await user.click(within(banner).getByRole('button', { name: /면접 종료/ }))
    const dialog = await screen.findByRole('alertdialog', { name: '면접을 종료할까요?' })
    await user.click(within(dialog).getByRole('button', { name: '계속 진행' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
    expect(getDb().session(LIVE)!.status).toBe('in_progress')

    await user.click(within(banner).getByRole('button', { name: '1시간 뒤 다시 알림' }))
    expect(screen.queryByTestId('long-open-banner')).toBeNull()
  })
})
