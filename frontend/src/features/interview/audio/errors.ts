/**
 * Short codes for microphone problems, shown on screen so they can be copied down by hand inside the
 * company network (docs/audio-input.md 6장). Browser-side codes are decided here; server-side ones
 * come with the server's message (src/interview_assistant/live/codes.py) and fall back to the text
 * below. `stop`: the microphone cannot run; otherwise it runs with something degraded.
 */
export interface AudioProblem {
  code: string
  message: string
  stop: boolean
}

const TABLE: Record<string, { message: string; stop: boolean }> = {
  'MIC-HTTPS': { message: 'HTTPS 주소가 아니라 브라우저가 마이크를 막습니다. https:// 주소(또는 이 PC의 localhost)로 여세요.', stop: true },
  'MIC-DENIED': { message: '마이크 권한이 거부되었습니다. 주소창 왼쪽 아이콘에서 마이크를 허용한 뒤 다시 켜세요. 회사 정책으로 막혔다면 담당자에게 알리세요.', stop: true },
  'MIC-NONE': { message: '마이크 장치를 찾지 못했습니다. 연결과 OS의 소리 입력 설정을 확인하세요.', stop: true },
  'MIC-BUSY': { message: '다른 프로그램이 마이크를 쓰고 있거나 장치를 열 수 없습니다.', stop: true },
  'MIC-UNSUPPORTED': { message: '이 브라우저는 마이크 녹음(getUserMedia·AudioWorklet)을 지원하지 않습니다. 최신 Chrome이나 Edge를 쓰세요.', stop: true },
  'MIC-FAILED': { message: '마이크를 켜지 못했습니다.', stop: true },
  'SAMPLE-FAILED': { message: '샘플 음성을 불러오지 못했습니다.', stop: true },
  'WS-BLOCKED': { message: 'WebSocket 연결이 막혀 HTTP로 나눠 보냅니다. 전사가 조금 늦을 수 있습니다.', stop: false },
  'WS-LOST': { message: 'WebSocket 연결이 끊겨 HTTP로 이어 보냅니다.', stop: false },
  'HTTP-FAILED': { message: '서버로 음성을 보내지 못합니다(WebSocket·HTTP 모두 실패). 네트워크·프록시 설정을 확인하세요.', stop: true },
  'NO-CONSENT': { message: '녹음 동의가 없는 면접입니다. 마이크를 쓰지 않고 답변을 수기로 기록합니다.', stop: true },
  'NOT-LIVE': { message: '진행 중인 면접이 아닙니다.', stop: true },
  'MIC-TAKEN': { message: '다른 창이나 기기에서 이 면접의 마이크를 이미 보내고 있습니다.', stop: true },
  'AUDIO-FORMAT': { message: '오디오 형식이 맞지 않습니다 (16kHz 모노 16비트 PCM만 받습니다).', stop: true },
  'VAD-MISSING': { message: '음성 구간(VAD) 모델을 쓸 수 없어 전사하지 않습니다. 녹음은 계속됩니다.', stop: false },
  'TURN-MISSING': { message: 'Smart Turn 모델이 없어 침묵 기준으로 답변 끝을 판정합니다.', stop: false },
  'STT-MISSING': { message: '실시간 STT 모델을 쓸 수 없어 전사하지 않습니다. 녹음은 계속됩니다.', stop: false },
  'STT-FORMAT': { message: '실시간 STT가 마이크 음성을 읽지 못합니다. 관리자 > 모델 설정을 확인하세요.', stop: false },
  'STT-FAILED': { message: '실시간 전사 중 오류가 났습니다. 답변은 수기로 기록할 수 있습니다.', stop: false },
  'REC-FAILED': { message: '녹음 파일을 쓰지 못했습니다. 서버의 저장 공간과 권한을 확인하세요.', stop: false },
}

export function problem(code: string, message?: string | null): AudioProblem {
  const known = TABLE[code]
  return { code, message: message || known?.message || code, stop: known?.stop ?? true }
}

/** getUserMedia's DOMException name -> code. */
export function micErrorCode(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') return 'MIC-DENIED'
  if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'DevicesNotFoundError') return 'MIC-NONE'
  if (name === 'NotReadableError' || name === 'AbortError' || name === 'TrackStartError') return 'MIC-BUSY'
  return 'MIC-FAILED'
}
