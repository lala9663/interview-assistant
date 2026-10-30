import { onScopeDispose, shallowRef, type Ref } from 'vue'

const TEXT_INPUTS = new Set(['text', 'search', 'email', 'number', 'password', 'tel', 'url', 'date', 'datetime-local', 'month', 'time', 'week'])

/** A field that takes typing: a digit pressed there is text, never a shortcut. */
export function isEditable(el: Element | null): boolean {
  if (!el) return false
  if (el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) return true
  if (el instanceof HTMLInputElement) return TEXT_INPUTS.has(el.type)
  return el instanceof HTMLElement && el.isContentEditable
}

/**
 * Whether a plain key (1-9, Shift+1-9, /) may act as a live-room shortcut: not while typing in a field,
 * not inside a dialog or an open list (the end dialog, the command palette, a select), and never with
 * Alt, Ctrl or ⌘, which belong to the microphone roles (Alt+1 / Alt+2) and the command palette (Ctrl+K).
 */
export function roomShortcut(e: KeyboardEvent): boolean {
  if (e.defaultPrevented || e.repeat || e.isComposing || e.altKey || e.ctrlKey || e.metaKey) return false
  const t = e.target instanceof Element ? e.target : null
  return !isEditable(t) && !t?.closest('[role="dialog"], [role="alertdialog"], [role="listbox"], [role="menu"]')
}

/** 1-9 from the number row or the keypad, else null. */
export function digitOf(e: KeyboardEvent): number | null {
  const m = /^(?:Digit|Numpad)([1-9])$/.exec(e.code)
  return m ? Number(m[1]) : null
}

/** Listen for keys on the window while the calling component is mounted. */
export function useWindowKeys(handler: (e: KeyboardEvent) => void) {
  window.addEventListener('keydown', handler)
  onScopeDispose(() => window.removeEventListener('keydown', handler))
}

/** True while focus is in a field that takes typing (the room's number keys rest meanwhile). */
export function useTyping(): Readonly<Ref<boolean>> {
  const typing = shallowRef(isEditable(document.activeElement))
  const update = () => (typing.value = isEditable(document.activeElement))
  // focusout fires before focus lands elsewhere: read the new element once it has.
  const later = () => queueMicrotask(update)
  document.addEventListener('focusin', update)
  document.addEventListener('focusout', later)
  onScopeDispose(() => {
    document.removeEventListener('focusin', update)
    document.removeEventListener('focusout', later)
  })
  return typing
}
