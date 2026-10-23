/**
 * Resolve a design token (`--series-1`, `var(--popover)`, …) to an `rgb()`/`rgba()` string for canvas
 * charts. Tokens may be oklch()/color-mix(), which the canvas understands but Chart.js's color helper
 * does not, so the browser converts them through a 1×1 canvas.
 */
let ctx: CanvasRenderingContext2D | null | undefined

export function resolveCssColor(token: string, fallback = '#888888'): string {
  if (typeof document === 'undefined') return fallback
  const name = token.startsWith('var(') ? token.slice(4, -1).trim() : token
  const value = name.startsWith('--') ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() : name
  if (!value) return fallback
  if (/^#[0-9a-f]{3,8}$/i.test(value)) return value
  if (ctx === undefined) ctx = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
  if (!ctx) return fallback
  ctx.clearRect(0, 0, 1, 1)
  ctx.fillStyle = fallback
  ctx.fillStyle = value
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a! / 255).toFixed(3)})`
}
