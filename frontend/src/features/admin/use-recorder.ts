import { onScopeDispose, ref } from 'vue'

export type RecorderState = 'idle' | 'recording' | 'done' | 'error'

const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']

function pickMime(): string {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') return ''
  return MIME_TYPES.find((m) => MediaRecorder.isTypeSupported(m)) ?? ''
}

export function extensionFor(mime: string): string {
  if (mime.includes('ogg')) return 'ogg'
  if (mime.includes('mp4')) return 'm4a'
  return 'webm'
}

/**
 * Browser microphone recording for the STT test: up to `maxSeconds`, with a live input level so the
 * admin can see the microphone works. The recording stays in the page until it is sent for a test.
 */
export function useRecorder(maxSeconds = 10) {
  const state = ref<RecorderState>('idle')
  const elapsed = ref(0)
  const level = ref(0)
  const error = ref<string | null>(null)
  const blob = ref<Blob | null>(null)
  const url = ref<string | null>(null)

  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let timer: ReturnType<typeof setInterval> | null = null
  let frame = 0

  function release() {
    if (timer) clearInterval(timer)
    timer = null
    cancelAnimationFrame(frame)
    stream?.getTracks().forEach((t) => t.stop())
    stream = null
    void audioContext?.close().catch(() => {})
    audioContext = null
    level.value = 0
  }

  function clear() {
    if (url.value) URL.revokeObjectURL(url.value)
    url.value = null
    blob.value = null
  }

  function meter(source: MediaStream) {
    if (typeof AudioContext === 'undefined') return
    audioContext = new AudioContext()
    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 512
    audioContext.createMediaStreamSource(source).connect(analyser)
    const data = new Uint8Array(analyser.fftSize)
    const tick = () => {
      analyser.getByteTimeDomainData(data)
      let sum = 0
      for (const v of data) sum += ((v - 128) / 128) ** 2
      level.value = Math.min(1, Math.sqrt(sum / data.length) * 4)
      frame = requestAnimationFrame(tick)
    }
    tick()
  }

  async function start() {
    clear()
    error.value = null
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      error.value = '이 브라우저는 마이크 녹음을 지원하지 않습니다. 파일로 테스트하세요.'
      state.value = 'error'
      return
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
    } catch {
      error.value = '마이크를 쓸 수 없습니다. 브라우저의 마이크 권한을 허용했는지 확인하세요.'
      state.value = 'error'
      return
    }
    const mime = pickMime()
    const chunks: Blob[] = []
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data)
    }
    recorder.onstop = () => {
      const type = recorder?.mimeType || mime || 'audio/webm'
      blob.value = new File(chunks, `recording.${extensionFor(type)}`, { type })
      url.value = URL.createObjectURL(blob.value)
      state.value = 'done'
      release()
    }
    meter(stream)
    recorder.start(250)
    state.value = 'recording'
    const startedAt = Date.now()
    elapsed.value = 0
    timer = setInterval(() => {
      elapsed.value = (Date.now() - startedAt) / 1000
      if (elapsed.value >= maxSeconds) stop()
    }, 100)
  }

  function stop() {
    if (timer) clearInterval(timer)
    timer = null
    if (recorder && recorder.state === 'recording') recorder.stop()
  }

  function reset() {
    stop()
    release()
    clear()
    elapsed.value = 0
    error.value = null
    state.value = 'idle'
  }

  onScopeDispose(reset)

  return { state, elapsed, level, error, blob, url, start, stop, reset, maxSeconds }
}
