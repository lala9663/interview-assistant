"""Short error codes for the microphone path, shown on the interview screen so that a problem seen
inside the company network can be copied down by hand (docs/audio-input.md 6장 lists them all,
browser-side ones included). The server sends `code` and the screen shows it next to the message.
"""

from __future__ import annotations

# Server-side codes (the browser has its own: MIC-DENIED, MIC-HTTPS, WS-BLOCKED ...).
NO_CONSENT = "NO-CONSENT"
NOT_LIVE = "NOT-LIVE"
MIC_TAKEN = "MIC-TAKEN"
AUDIO_FORMAT = "AUDIO-FORMAT"
VAD_MISSING = "VAD-MISSING"
TURN_MISSING = "TURN-MISSING"
STT_MISSING = "STT-MISSING"
STT_FORMAT = "STT-FORMAT"
STT_FAILED = "STT-FAILED"
REC_FAILED = "REC-FAILED"

MESSAGES: dict[str, str] = {
    NO_CONSENT: "녹음 동의가 없는 면접입니다. 마이크를 쓰지 않고 답변을 수기로 기록합니다.",
    NOT_LIVE: "진행 중인 면접이 아닙니다.",
    MIC_TAKEN: "다른 창이나 기기에서 이 면접의 마이크를 이미 보내고 있습니다.",
    AUDIO_FORMAT: "오디오 형식이 맞지 않습니다 (16kHz 모노 16비트 PCM만 받습니다).",
    VAD_MISSING: "음성 구간(VAD) 모델을 쓸 수 없어 전사하지 않습니다. 녹음은 계속됩니다.",
    TURN_MISSING: "Smart Turn 모델이 없어 침묵 기준으로 답변 끝을 판정합니다.",
    STT_MISSING: "실시간 STT 모델을 쓸 수 없어 전사하지 않습니다. 녹음은 계속됩니다.",
    STT_FORMAT: "실시간 STT가 마이크 음성을 읽지 못합니다. 관리자 > 모델 설정을 확인하세요.",
    STT_FAILED: "실시간 전사 중 오류가 났습니다. 답변은 수기로 기록할 수 있습니다.",
    REC_FAILED: "녹음 파일을 쓰지 못했습니다. 저장 공간과 권한을 확인하세요.",
}


def describe(code: str) -> dict[str, str]:
    return {"code": code, "message": MESSAGES.get(code, code)}
