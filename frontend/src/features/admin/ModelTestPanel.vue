<script setup lang="ts">
import { CircleAlertIcon, CircleCheckIcon, FileAudioIcon, MicIcon, PlayIcon, RotateCcwIcon, SquareIcon } from '@lucide/vue'
import { useMutation } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'

import { endpoints } from '@/api/endpoints'
import type { ModelSpec, ModelTestResult } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { errorMessage } from '@/lib/toast'

import { takesAudio } from './labels'
import { useRecorder } from './use-recorder'

/**
 * 연결 테스트. Runs only on the button. STT (and diarization) take the server's built-in Korean sample,
 * a 5–10 second microphone recording, or a file; the audio is deleted on the server after the test.
 */
const props = defineProps<{ role: string; spec: ModelSpec; confirmExternal: boolean }>()
const emit = defineEmits<{ result: [result: ModelTestResult | null] }>()

type Source = 'sample' | 'mic' | 'file'
const source = ref<Source>('sample')
const file = ref<File | null>(null)
const recorder = useRecorder(10)
const MIN_SECONDS = 3

const run = reactive(
  useMutation({
    mutationFn: () => {
      const audio = !takesAudio(props.role) || source.value === 'sample' ? null : source.value === 'mic' ? recorder.blob.value : file.value
      return endpoints.testModel(props.role, props.spec, { confirmExternal: props.confirmExternal, audio })
    },
    onSuccess: (r) => emit('result', r),
    onError: () => emit('result', null),
  }),
)

// A different spec needs a new test.
watch(
  () => JSON.stringify(props.spec),
  () => {
    run.reset()
    emit('result', null)
  },
)

const audioReady = computed(() => {
  if (!takesAudio(props.role) || source.value === 'sample') return true
  if (source.value === 'mic') return recorder.state.value === 'done' && recorder.elapsed.value >= MIN_SECONDS
  return file.value !== null
})

const result = computed(() => run.data)
const out = computed(() => (result.value?.output ?? {}) as Record<string, unknown>)
const num = (k: string) => (typeof out.value[k] === 'number' ? (out.value[k] as number) : null)
const str = (k: string) => (typeof out.value[k] === 'string' ? (out.value[k] as string) : null)

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="takesAudio(role)" class="space-y-3">
      <Segmented :model-value="source" aria-label="테스트 음성" @update:model-value="(v) => (source = v as Source)">
        <SegmentedItem value="sample">내장 샘플</SegmentedItem>
        <SegmentedItem value="mic">마이크로 테스트</SegmentedItem>
        <SegmentedItem value="file">파일</SegmentedItem>
      </Segmented>

      <p v-if="source === 'sample'" class="text-xs leading-relaxed text-muted-foreground">
        한국어 낭독 11.5초 (FLEURS, CC BY 4.0). 정답 전사와 비교해 글자 오류율(CER)도 보여 줍니다.
      </p>

      <div v-else-if="source === 'mic'" class="space-y-2 rounded-lg border bg-subtle p-3" data-testid="mic-recorder">
        <div class="flex flex-wrap items-center gap-2">
          <Button v-if="recorder.state.value !== 'recording'" size="sm" variant="outline" @click="recorder.start()">
            <MicIcon />
            {{ recorder.state.value === 'done' ? '다시 녹음' : '녹음 시작' }}
          </Button>
          <Button v-else size="sm" variant="destructive" :disabled="recorder.elapsed.value < MIN_SECONDS" @click="recorder.stop()">
            <SquareIcon />
            멈춤
          </Button>
          <span class="text-xs text-muted-foreground tabular">{{ recorder.elapsed.value.toFixed(1) }} / {{ recorder.maxSeconds }}초</span>
          <div class="h-1.5 w-28 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <div class="h-full rounded-full bg-live transition-[width] duration-75" :style="{ width: `${Math.round(recorder.level.value * 100)}%` }"></div>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">5~10초 동안 한국어로 말해 보세요 ({{ MIN_SECONDS }}초 이상, 10초에서 자동으로 멈춤). 녹음은 테스트에만 쓰고 저장하지 않습니다.</p>
        <audio v-if="recorder.url.value" :src="recorder.url.value" controls class="h-8 w-full" />
        <p v-if="recorder.error.value" class="text-xs text-danger">{{ recorder.error.value }}</p>
      </div>

      <div v-else class="space-y-1.5">
        <input
          type="file"
          accept="audio/*,.wav,.webm,.ogg,.mp3,.m4a,.flac"
          aria-label="테스트 음성 파일"
          class="flex h-9 w-full min-w-0 cursor-pointer rounded-md border border-input bg-card px-3 py-1.5 text-sm text-muted-foreground outline-none file:mr-3 file:cursor-pointer file:border-0 file:bg-transparent file:p-0 file:text-sm file:font-medium file:text-foreground"
          @change="pick"
        />
        <p class="text-xs text-muted-foreground">WAV, WebM, MP3, M4A … 60초·10MB 이하.</p>
      </div>
    </div>
    <p v-else-if="role.startsWith('llm.')" class="text-xs leading-relaxed text-muted-foreground">
      지원자 데이터가 없는 고정 문장으로 구조화 출력(JSON)과 간단한 지시 수행을 확인합니다. 호출은 감사 로그에 남습니다.
    </p>
    <p v-else class="text-xs text-muted-foreground">짧은 문장 두 개를 임베딩해 벡터 차원을 확인합니다.</p>

    <div class="flex items-center gap-2">
      <Button size="sm" :disabled="!audioReady || run.isPending" data-testid="run-test" @click="run.mutate()">
        <component :is="run.data ? RotateCcwIcon : PlayIcon" />
        {{ run.isPending ? '테스트 중…' : run.data ? '다시 테스트' : '연결 테스트' }}
      </Button>
      <span v-if="run.isPending && takesAudio(role)" class="text-xs text-muted-foreground">로컬 모델은 처음 불러올 때 수십 초 걸릴 수 있습니다.</span>
    </div>

    <p v-if="run.isError" class="flex items-start gap-1.5 text-[13px] text-danger" role="alert">
      <CircleAlertIcon class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {{ errorMessage(run.error) }}
    </p>

    <div v-if="result" class="space-y-3 rounded-lg border bg-card p-3.5" data-testid="test-result" :data-ok="result.ok">
      <div class="flex flex-wrap items-center gap-2">
        <Badge v-if="result.ok" variant="success"><CircleCheckIcon aria-hidden="true" />통과</Badge>
        <Badge v-else variant="danger"><CircleAlertIcon aria-hidden="true" />실패</Badge>
        <span class="text-[13px]">{{ result.summary }}</span>
      </div>
      <div class="flex flex-wrap gap-1.5 text-xs">
        <Badge variant="outline" class="font-mono">{{ result.model }}</Badge>
        <Badge variant="outline" class="tabular">처리 {{ (result.latency_ms / 1000).toFixed(1) }}초</Badge>
        <Badge v-if="num('audio_seconds') !== null" variant="outline" class="tabular">음성 {{ num('audio_seconds')!.toFixed(1) }}초</Badge>
        <Badge v-if="num('realtime_factor') !== null" variant="outline" class="tabular">음성 길이의 {{ num('realtime_factor')!.toFixed(2) }}배 시간</Badge>
        <Badge v-if="num('cer') !== null" variant="outline" class="tabular">CER {{ (num('cer')! * 100).toFixed(1) }}%</Badge>
        <Badge v-if="num('dimensions') !== null" variant="outline" class="tabular">{{ num('dimensions') }}차원</Badge>
        <Badge v-if="result.audio === 'upload'" variant="outline"><FileAudioIcon aria-hidden="true" />올린 음성</Badge>
      </div>
      <div v-if="str('text') !== null" class="space-y-1.5">
        <p class="text-xs font-medium text-muted-foreground">전사 결과</p>
        <p class="rounded-md bg-subtle px-3 py-2 text-sm leading-relaxed" data-testid="transcript">{{ str('text') || '(없음)' }}</p>
        <template v-if="str('expected_text')">
          <p class="text-xs font-medium text-muted-foreground">샘플 정답</p>
          <p class="px-3 text-[13px] leading-relaxed text-muted-foreground">{{ str('expected_text') }}</p>
        </template>
      </div>
      <pre v-if="out.structured" class="overflow-x-auto rounded-md bg-subtle px-3 py-2 text-xs">{{ JSON.stringify(out.structured, null, 2) }}</pre>
      <p v-if="result.error" class="text-xs text-danger">{{ result.error }}</p>
    </div>
  </div>
</template>
