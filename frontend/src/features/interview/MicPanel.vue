<script setup lang="ts">
import { AudioLinesIcon, MicIcon, MicOffIcon, SlidersHorizontalIcon, TriangleAlertIcon } from '@lucide/vue'
import { useQuery } from '@tanstack/vue-query'
import { computed, onScopeDispose, ref } from 'vue'
import { toast } from 'vue-sonner'

import { endpoints } from '@/api/endpoints'
import type { MicRole, QAItem, StreamStatus } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { errorMessage } from '@/lib/toast'
import { cn } from '@/lib/utils'

import { problem, type AudioProblem } from './audio/errors'
import { DEFAULT_MIC_SETTINGS, useMicSettings, type MicSource } from './audio/settings'
import { useMicrophone } from './audio/use-microphone'

/**
 * 마이크: on/off with the input level, 질문 중 / 답변 듣는 중 for one microphone in a face-to-face interview
 * (Alt+1 / Alt+2), the browser's audio processing and the input (microphone or a diagnostic sample), and
 * every problem as a short code. Without recording consent the microphone stays off (manual mode).
 */
const props = defineProps<{ sessionId: string; manual: boolean; status: StreamStatus | null }>()
const emit = defineEmits<{ question: [qa: QAItem] }>()

const settings = useMicSettings()
const mic = useMicrophone(props.sessionId, { onQuestion: (qa) => emit('question', qa) })
const state = mic.state
const settingsOpen = ref(false)
const samples = useQuery({ queryKey: ['audio-samples'], queryFn: endpoints.audioSamples, enabled: () => settingsOpen.value, staleTime: Infinity })

const on = computed(() => state.value.status === 'on')
const busy = computed(() => state.value.status === 'starting')
// Codes from this browser and from the server (status: VAD-MISSING, STT-MISSING ...), each once.
const problems = computed<AudioProblem[]>(() => {
  const found = new Map<string, AudioProblem>()
  if (props.manual) found.set('NO-CONSENT', problem('NO-CONSENT'))
  if (state.value.error) found.set(state.value.error.code, state.value.error)
  for (const n of state.value.notices) found.set(n.code, n)
  if (on.value) {
    for (const code of props.status?.mic?.notices ?? []) if (!found.has(code)) found.set(code, problem(code))
    const error = props.status?.error
    if (error && !found.has(error.code)) found.set(error.code, problem(error.code, error.message))
  }
  return [...found.values()]
})
// The server switches back to the candidate when a question is typed or picked: its status wins.
const role = computed<MicRole>(() => (on.value && props.status?.mic?.role) || state.value.role)

function toggle() {
  if (on.value || busy.value) mic.stop()
  else void mic.start(settings.value)
}

async function switchRole(next: string) {
  if (!on.value || next === role.value) return
  try {
    await mic.setRole(next as MicRole)
  } catch (e) {
    toast.error('전환하지 못했습니다', { description: errorMessage(e) })
  }
}

function onKey(e: KeyboardEvent) {
  if (!e.altKey || e.ctrlKey || e.metaKey || !on.value) return
  if (e.code === 'Digit1') void switchRole('interviewer')
  else if (e.code === 'Digit2') void switchRole('candidate')
  else return
  e.preventDefault()
}
window.addEventListener('keydown', onKey)
onScopeDispose(() => window.removeEventListener('keydown', onKey))

const resetSettings = () => (settings.value = { ...DEFAULT_MIC_SETTINGS })
const PROCESSING = [
  { key: 'echoCancellation', label: '에코 제거 (AEC)', help: '스피커로 나간 소리를 마이크 입력에서 뺍니다. 기본 켬.' },
  { key: 'noiseSuppression', label: '잡음 억제 (NS)', help: '전사 정확도를 떨어뜨릴 수 있어 기본 끔. 잡음이 심한 방에서만 재 보고 켭니다.' },
  { key: 'autoGainControl', label: '자동 음량 (AGC)', help: '소리 크기를 자동으로 바꿉니다. STT 앞에서는 기본 끔.' },
] as const
</script>

<template>
  <div class="border-b bg-card/30" data-testid="mic-panel">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
      <Button
        size="sm"
        :variant="on ? 'secondary' : 'default'"
        :disabled="manual"
        :aria-pressed="on"
        data-testid="mic-toggle"
        @click="toggle"
      >
        <MicOffIcon v-if="on || busy" aria-hidden="true" />
        <MicIcon v-else aria-hidden="true" />
        {{ busy ? '켜는 중…' : on ? '마이크 끄기' : '마이크 켜기' }}
      </Button>

      <div class="flex items-center gap-2" :class="!on && 'opacity-50'">
        <div class="h-2 w-20 overflow-hidden rounded-full bg-muted" role="meter" aria-label="입력 음량" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Math.round(state.level * 100)">
          <div class="h-full rounded-full bg-success transition-[width] duration-100" :style="{ width: `${Math.round(state.level * 100)}%` }" />
        </div>
        <span :class="cn('flex items-center gap-1 text-[12px] whitespace-nowrap', state.speaking ? 'text-live' : 'text-muted-foreground')" data-testid="mic-speaking">
          <AudioLinesIcon class="size-3.5" aria-hidden="true" />{{ state.speaking ? '말소리' : '조용함' }}
        </span>
      </div>

      <Segmented :model-value="role" :disabled="!on" aria-label="마이크로 듣는 사람" @update:model-value="switchRole">
        <SegmentedItem value="interviewer" data-testid="role-interviewer">질문 중 <Kbd class="hidden lg:inline-flex">Alt 1</Kbd></SegmentedItem>
        <SegmentedItem value="candidate" data-testid="role-candidate">답변 듣는 중 <Kbd class="hidden lg:inline-flex">Alt 2</Kbd></SegmentedItem>
      </Segmented>

      <div class="ml-auto flex items-center gap-2">
        <Badge v-if="state.source === 'sample' && on" variant="outline">샘플 음성</Badge>
        <Badge v-if="state.transport" variant="outline" class="font-mono" data-testid="mic-transport">{{ state.transport === 'websocket' ? 'WebSocket' : 'HTTP 대체' }}</Badge>
        <Button variant="ghost" size="icon-sm" aria-label="마이크 설정" :disabled="manual" @click="settingsOpen = true">
          <SlidersHorizontalIcon />
        </Button>
      </div>
    </div>

    <ul v-if="problems.length" class="space-y-1 px-4 pb-2" aria-live="polite">
      <li
        v-for="p in problems"
        :key="p.code"
        :role="p.stop ? 'alert' : undefined"
        :class="cn('flex items-start gap-2 rounded-md px-2.5 py-1.5 text-[12.5px]', p.stop ? 'bg-[color-mix(in_oklch,var(--danger)_10%,transparent)]' : 'bg-[color-mix(in_oklch,var(--warning)_10%,transparent)]')"
        :data-testid="`mic-problem-${p.code}`"
      >
        <TriangleAlertIcon :class="cn('mt-0.5 size-3.5 shrink-0', p.stop ? 'text-danger' : 'text-warning')" aria-hidden="true" />
        <span><code class="mr-1.5 rounded bg-card px-1 font-mono text-[11.5px] font-semibold">{{ p.code }}</code>{{ p.message }}</span>
      </li>
    </ul>

    <Dialog v-model:open="settingsOpen">
      <DialogContent class="max-w-md">
        <DialogHeader>
          <DialogTitle>마이크 설정</DialogTitle>
          <DialogDescription>이 브라우저에 저장됩니다. 바꾼 설정은 마이크를 다시 켤 때 적용됩니다.</DialogDescription>
        </DialogHeader>
        <div class="space-y-4 text-[13px]">
          <div class="space-y-1.5">
            <Label for="mic-source">입력</Label>
            <Select :model-value="settings.source" @update:model-value="(v) => (settings.source = String(v) as MicSource)">
              <SelectTrigger id="mic-source"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="microphone">마이크</SelectItem>
                <SelectItem value="sample">진단용 샘플 음성 (마이크 대신)</SelectItem>
              </SelectContent>
            </Select>
            <p v-if="settings.source === 'sample'" class="text-[12px] text-muted-foreground">
              저장된 한국어 녹음을 마이크처럼 흘려보냅니다. 마이크가 막혔을 때 나머지 경로(전송·전사·답변 끝·꼬리질문)를 확인할 때 씁니다.
              녹음 파일에는 남지 않지만 전사는 이 면접의 답변으로 기록되니 시험용 면접에서만 쓰세요.
            </p>
            <Select v-if="settings.source === 'sample'" :model-value="settings.sample" @update:model-value="(v) => (settings.sample = String(v))">
              <SelectTrigger aria-label="샘플 음성"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem v-for="s in samples.data.value ?? []" :key="s.name" :value="s.name">{{ s.label }} · {{ s.seconds }}초</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div v-for="p in PROCESSING" :key="p.key" class="flex items-start justify-between gap-4" :class="settings.source === 'sample' && 'opacity-50'">
            <div>
              <Label :for="`mic-${p.key}`">{{ p.label }}</Label>
              <p class="text-[12px] text-muted-foreground">{{ p.help }}</p>
            </div>
            <Switch :id="`mic-${p.key}`" v-model="settings[p.key]" :disabled="settings.source === 'sample'" />
          </div>
          <Button variant="outline" size="sm" @click="resetSettings">기본값으로</Button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>
