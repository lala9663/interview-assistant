import { screen } from '@testing-library/vue'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { renderRoute } from '@/test/render'

import CommandPalette from './CommandPalette.vue'

describe('<CommandPalette>', () => {
  it('opens, finds a candidate by pseudonym and lists only exact substring matches', async () => {
    const user = userEvent.setup()
    await renderRoute(CommandPalette, { path: '/', url: '/', props: { open: true } })
    const input = await screen.findByPlaceholderText(/화면, 지원자/)
    await screen.findAllByText('CAND-0007')
    await user.type(input, 'cand-0001')
    const options = screen.getAllByRole('option')
    expect(options.length).toBeGreaterThan(0)
    for (const o of options) expect(o).toHaveTextContent('CAND-0001')
  })
})
