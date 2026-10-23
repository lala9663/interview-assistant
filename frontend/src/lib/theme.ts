import { computed, readonly, ref, watchEffect } from 'vue'

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'ia-theme'

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // storage unavailable (private mode): fall through
  }
  return 'system'
}

function systemTheme(): ResolvedTheme {
  // Dark is the designed-first theme: use it unless the system explicitly asks for light.
  if (typeof window === 'undefined' || !window.matchMedia) return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

// App-wide singleton state: one theme per document, so no provider is needed.
const preference = ref<ThemePreference>(readPreference())
const system = ref<ResolvedTheme>(systemTheme())
const resolved = computed<ResolvedTheme>(() => (preference.value === 'system' ? system.value : preference.value))

function setPreference(p: ThemePreference) {
  preference.value = p
  try {
    localStorage.setItem(STORAGE_KEY, p)
  } catch {
    // ignore
  }
}

let started = false

/** Follow the OS setting and keep `<html class="dark">` in sync. Called once at startup. */
export function initTheme() {
  if (started || typeof window === 'undefined') return
  started = true
  if (window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    mq.addEventListener('change', () => (system.value = mq.matches ? 'light' : 'dark'))
  }
  watchEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', resolved.value === 'dark')
    root.style.colorScheme = resolved.value
  })
}

export function useTheme() {
  return { preference: readonly(preference), resolved, setPreference }
}
