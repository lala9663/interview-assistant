import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { renderRoute } from '@/test/render'

import { CommandPalette } from './command-palette'

describe('<CommandPalette>', () => {
  it('opens, finds a candidate by pseudonym and lists only exact substring matches', async () => {
    const user = userEvent.setup()
    renderRoute(<CommandPalette open onOpenChange={vi.fn()} />, { path: '/', url: '/' })
    const input = await screen.findByPlaceholderText(/화면, 지원자/)
    await screen.findAllByText('CAND-0007')
    await user.type(input, 'cand-0001')
    const options = screen.getAllByRole('option')
    expect(options.length).toBeGreaterThan(0)
    for (const o of options) expect(o).toHaveTextContent('CAND-0001')
  })
})
