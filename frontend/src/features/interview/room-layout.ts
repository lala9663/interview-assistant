import { computed, onMounted, onScopeDispose, shallowRef, type Ref } from 'vue'

/**
 * The room's own width, not the window's (the app menu may be open beside it). From this width the room
 * has three columns: 지원자·사전 질문 | 전사 | 꼬리질문. A 1366 px laptop at 125% (1093 px) still gets them.
 */
export const WIDE_MIN_PX = 1080
/** From this width two columns: 전사 | 꼬리질문, with 사전 질문 and 지원자 as tabs beside 꼬리질문. Below, one column. */
export const TWO_COLUMNS_MIN_PX = 760

export type RoomLayout = 'wide' | 'medium' | 'narrow'

/** null: not measured (no layout engine, as in tests) — the full layout. */
export function roomLayout(width: number | null): RoomLayout {
  if (width === null || width >= WIDE_MIN_PX) return 'wide'
  return width >= TWO_COLUMNS_MIN_PX ? 'medium' : 'narrow'
}

/** Follows the element's width with a ResizeObserver. */
export function useRoomLayout(el: Readonly<Ref<HTMLElement | undefined>>) {
  const width = shallowRef<number | null>(null)
  let observer: ResizeObserver | undefined
  onMounted(() => {
    const node = el.value
    if (!node) return
    if (node.clientWidth > 0) width.value = node.clientWidth
    observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w) width.value = w
    })
    observer.observe(node)
  })
  onScopeDispose(() => observer?.disconnect())
  return computed(() => roomLayout(width.value))
}
