import { ref, watch } from 'vue'

/**
 * The microphone settings of this browser (localStorage). Defaults follow docs/reference/audio-quality.md
 * 5장: echo cancellation on (it removes only what the speakers play), noise suppression and automatic
 * gain off in front of STT (both change the sound in ways that can raise STT errors; measure before
 * turning them on). `source: 'sample'` plays a bundled recording into the same path instead of the
 * microphone: for the preview browser, automated checks, and diagnosing a blocked microphone.
 */
export type MicSource = 'microphone' | 'sample'

export interface MicSettings {
  echoCancellation: boolean
  noiseSuppression: boolean
  autoGainControl: boolean
  source: MicSource
  sample: string
}

export const DEFAULT_MIC_SETTINGS: MicSettings = {
  echoCancellation: true,
  noiseSuppression: false,
  autoGainControl: false,
  source: 'microphone',
  sample: 'answer-pauses',
}

const KEY = 'ia.mic-settings'

function load(): MicSettings {
  try {
    const raw = window.localStorage.getItem(KEY)
    const saved = raw ? (JSON.parse(raw) as Partial<MicSettings>) : {}
    return { ...DEFAULT_MIC_SETTINGS, ...saved }
  } catch {
    return { ...DEFAULT_MIC_SETTINGS }
  }
}

const settings = ref<MicSettings>(load())
watch(
  settings,
  (value) => {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(value))
    } catch {
      // private window or blocked storage: the settings last for this page only
    }
  },
  { deep: true },
)

export function useMicSettings() {
  return settings
}
