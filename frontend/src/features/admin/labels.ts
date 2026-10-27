import { CloudIcon, GlobeIcon, MonitorIcon } from '@lucide/vue'
import type { Component } from 'vue'

import type { DataLocation, ModelChangeKind, ModelImpl, ModelOptionField, ModelOptionValue, ModelRole, ModelSpec } from '@/api/types'
import { MODEL_ROLE_KIND } from '@/api/types'

export const DATA_LOCATION: Record<DataLocation, { label: string; hint: string; variant: 'success' | 'brand' | 'warning'; icon: Component }> = {
  local: { label: '이 PC', hint: '데이터가 이 서버 밖으로 나가지 않습니다.', variant: 'success', icon: MonitorIcon },
  gcp: { label: '사내 GCP', hint: '사내 GCP 프로젝트 안에서 처리합니다.', variant: 'brand', icon: CloudIcon },
  external: { label: '외부', hint: '회사 밖 API로 데이터를 보냅니다. 경고 확인과 사유가 있어야 적용됩니다.', variant: 'warning', icon: GlobeIcon },
}

export const CHANGE_KIND_LABEL: Record<ModelChangeKind, string> = { initial: '처음 설정', apply: '변경', rollback: '되돌림' }

export const kindOf = (role: string): ModelImpl['kind'] => MODEL_ROLE_KIND[role as ModelRole] ?? (role.split('.')[0] as ModelImpl['kind'])

/** "STT 사후를", "LLM 주 모델을": the object particle after the last Hangul syllable. */
export function withObjectParticle(word: string): string {
  const code = word.charCodeAt(word.length - 1) - 0xac00
  if (code < 0 || code > 11171) return `${word}을(를)`
  return `${word}${code % 28 ? '을' : '를'}`
}

/** Roles that take a voice sample in the connection test. */
export const takesAudio = (role: string) => role.startsWith('stt.') || role === 'diarization'

/** 서류 읽기 roles: tested by reading a document (built-in fictional resume or a file). */
export const takesDocument = (role: string) => role.startsWith('document.')

export const READ_METHOD_LABEL: Record<string, string> = { text: '텍스트 층', ocr: 'OCR', held: '보류' }
export const PICTURE_LABEL: Record<string, string> = {
  photo: '증명사진: 읽지 않고 버림',
  ocr: 'OCR로 읽음',
  skipped: '읽지 않음 (설정)',
  small: '너무 작아 건너뜀',
  failed: 'OCR 실패',
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return '–'
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}GB`
  if (n >= 1e6) return `${Math.round(n / 1e6)}MB`
  return `${Math.max(1, Math.round(n / 1e3))}KB`
}

/** Fields of `impl` that apply to `role`. */
export const fieldsFor = (impl: ModelImpl, role: string): ModelOptionField[] => impl.options.filter((f) => f.roles.length === 0 || f.roles.includes(role))

/** The option values a change dialog starts from: the current spec for the current impl, else the impl's defaults for the role. */
export function initialOptions(impl: ModelImpl, role: ModelRole, current: ModelSpec | null): Record<string, ModelOptionValue> {
  const values: Record<string, ModelOptionValue> = {}
  for (const f of fieldsFor(impl, role)) {
    if (f.default !== null) values[f.key] = f.default
  }
  Object.assign(values, impl.role_defaults[role] ?? {})
  if (current && current.impl === impl.impl) {
    for (const f of fieldsFor(impl, role)) {
      const v = current.options[f.key]
      if (v !== undefined) values[f.key] = v
    }
  }
  return values
}

/** The "model" choice field whose choices are downloadable weights (faster-whisper sizes). */
export const weightsField = (impl: ModelImpl) => impl.options.find((f) => f.key === 'model' && f.choices.some((c) => c.size_bytes))

export const ROLE_SHORT: Record<string, string> = {
  'stt.streaming': '실시간',
  'stt.batch': '사후',
  'llm.primary': '주 모델',
  'llm.screening': '선별용',
  'document.ocr': 'OCR',
  'document.reading': '읽기 방식',
  embedding: '임베딩',
}
