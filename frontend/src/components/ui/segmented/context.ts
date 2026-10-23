import type { ComputedRef, InjectionKey } from 'vue'

/** Selected value of the enclosing <Segmented>, read by each item for its radio state. */
export const SEGMENTED_VALUE: InjectionKey<ComputedRef<string | undefined>> = Symbol('segmented-value')
