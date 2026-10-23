import { onScopeDispose, shallowRef, type Ref } from 'vue'

/** Current time, updated every `intervalMs` while the calling component is mounted. */
export function useNow(intervalMs = 1000): Readonly<Ref<Date>> {
  const now = shallowRef(new Date())
  const t = setInterval(() => (now.value = new Date()), intervalMs)
  onScopeDispose(() => clearInterval(t))
  return now
}
