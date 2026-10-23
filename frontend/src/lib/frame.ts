/**
 * Coalesce bursts of state writes into one commit per animation frame. Streams (transcript partials,
 * follow-up tokens) emit per token; Vue would otherwise re-render after every event, where React's
 * scheduler batched them. A timeout backs up the frame so a hidden tab (no frames) still commits.
 * `flush` commits right away (connection changes, user actions).
 */
export function frameBatch(commit: () => void, maxDelayMs = 100) {
  let scheduled = false
  const run = () => {
    if (!scheduled) return
    scheduled = false
    commit()
  }
  return {
    schedule() {
      if (scheduled) return
      scheduled = true
      if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run)
      setTimeout(run, maxDelayMs)
    },
    flush() {
      scheduled = false
      commit()
    },
  }
}
