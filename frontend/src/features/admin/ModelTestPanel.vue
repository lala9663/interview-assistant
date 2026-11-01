<script setup lang="ts">
import { CircleAlertIcon, CircleCheckIcon, FileAudioIcon, FileTextIcon, MicIcon, PlayIcon, RotateCcwIcon, SquareIcon } from '@lucide/vue'
import { useMutation } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'

import { endpoints } from '@/api/endpoints'
import type { ModelSpec, ModelTestResult, ReadingTestOutput } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { errorMessage } from '@/lib/toast'

import { FAILURE_LABEL, PICTURE_LABEL, READ_METHOD_LABEL, takesAudio, takesDocument } from './labels'
import { useRecorder } from './use-recorder'

/**
 * 연결 테스트. Runs only on the button. STT (and diarization) take the server's built-in Korean sample,
 * a 5–10 second microphone recording, or a file; the audio is deleted on the server after the test.
 * 서류 읽기 roles read the server's built-in fictional resume or a file: the answer shows how each page
 * was read and a de-identified preview, never the raw text; the file is deleted after the test.
 */
const props = defineProps<{ role: string; spec: ModelSpec; confirmExternal: boolean }>()
const emit = defineEmits<{ result: [result: ModelTestResult | null] }>()

type Source = 'sample' | 'mic' | 'file'
const source = ref<Source>('sample')
const file = ref<File | null>(null)
const docSource = ref<'sample' | 'file'>('sample')
const docFile = ref<File | null>(null)
const docName = ref('')
const DOC_ACCEPT = '.pdf,.docx,.pptx,.html,.htm,.hwp,.hwpx,.doc,.ppt,.jpg,.jpeg,.png'
const SAMPLE_NOTE: Record<string, string> = {
  'document.reading': '가상 지원서 합본 PDF: 1쪽은 텍스트와 자격증 사본 그림·증명사진, 2쪽은 스캔.',
  'document.ocr': '화면 캡처로 저장한 가상 이력서 PNG (정답과 비교한 글자 오류율도 보여 줍니다).',
  'document.pdf': '한글 글꼴의 ToUnicode가 깨진 가상 이력서 PDF (텍스트 층 깨짐 판정 → OCR).',
  'document.hwp': '머리글·각주·숨은 설명·흰 글씨·자격증 그림이 든 가상 이력서 HWPX.',
  'document.legacy': 'LibreOffice로 저장한 가상 이력서 Word 97-2003 (.doc).',
}
const recorder = useRecorder(10)
const MIN_SECONDS = 3

const run = reactive(
  useMutation({
    mutationFn: () => {
      if (takesDocument(props.role)) {
        const document = docSource.value === 'file' ? docFile.value : null
        return endpoints.testModel(props.role, props.spec, { confirmExternal: props.confirmExternal, document, name: document ? docName.value.trim() : '' })
      }
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
  if (takesDocument(props.role)) return docSource.value === 'sample' || docFile.value !== null
  if (!takesAudio(props.role) || source.value === 'sample') return true
  if (source.value === 'mic') return recorder.state.value === 'done' && recorder.elapsed.value >= MIN_SECONDS
  return file.value !== null
})

const result = computed(() => run.data)
const out = computed(() => (result.value?.output ?? {}) as Record<string, unknown>)
const num = (k: string) => (typeof out.value[k] === 'number' ? (out.value[k] as number) : null)
const str = (k: string) => (typeof out.value[k] === 'string' ? (out.value[k] as string) : null)
const servedModels = computed(() => (Array.isArray(out.value.server_models) ? (out.value.server_models as string[]) : null))

function pick(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

function pickDocument(e: Event) {
  docFile.value = (e.target as HTMLInputElement).files?.[0] ?? null
}

const reading = computed(() => (takesDocument(props.role) && result.value ? (result.value.output as unknown as ReadingTestOutput) : null))
const percent = (v: number | null | undefined) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : '–')
const seconds = (ms: number | null | undefined) => (typeof ms === 'number' ? `${(ms / 1000).toFixed(1)}초` : '–')
const signed = (db: number) => (db > 0 ? `+${db.toFixed(1)}` : db.toFixed(1))
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
        한국어 낭독 11.5초 (FLEURS, CC BY 4.0).
        {{ role.startsWith('stt.') ? '정답 전사와 비교해 글자 오류율(CER)도 보여 줍니다.' : role === 'audio.denoise' ? '조용한 녹음이라 줄일 잡음이 적습니다. 소음 있는 방에서 마이크로 녹음해 보면 억제 정도가 보입니다.' : '' }}
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
    <div v-else-if="takesDocument(role)" class="space-y-3">
      <Segmented :model-value="docSource" aria-label="테스트 문서" @update:model-value="(v) => (docSource = v as 'sample' | 'file')">
        <SegmentedItem value="sample">내장 샘플</SegmentedItem>
        <SegmentedItem value="file">파일 올리기</SegmentedItem>
      </Segmented>
      <p v-if="docSource === 'sample'" class="text-xs leading-relaxed text-muted-foreground">{{ SAMPLE_NOTE[role] }} 모든 인물과 연락처는 지어낸 것입니다.</p>
      <div v-else class="space-y-2">
        <input
          type="file"
          :accept="DOC_ACCEPT"
          aria-label="테스트 문서 파일"
          data-testid="document-file"
          class="flex h-9 w-full min-w-0 cursor-pointer rounded-md border border-input bg-card px-3 py-1.5 text-sm text-muted-foreground outline-none file:mr-3 file:cursor-pointer file:border-0 file:bg-transparent file:p-0 file:text-sm file:font-medium file:text-foreground"
          @change="pickDocument"
        />
        <Input v-model="docName" aria-label="지원자 이름 (비식별화용, 선택)" placeholder="지원자 이름 (선택: 미리보기에서 가릴 이름)" autocomplete="off" />
        <p class="text-xs text-muted-foreground">
          PDF·DOCX·PPTX·HTML·HWP·HWPX·DOC·PPT·JPG·PNG, 10MB 이하. 결과에는 비식별화된 미리보기만 나오고 원문은 보여 주지 않습니다. 파일은 테스트가 끝나면 지웁니다.
        </p>
      </div>
    </div>
    <p v-else-if="role.startsWith('llm.')" class="text-xs leading-relaxed text-muted-foreground">
      지원자 데이터가 없는 고정 문장으로 구조화 출력(JSON)과 간단한 지시 수행, 꼬리질문처럼 스트리밍으로 받을 때의 첫 토큰 시간을 확인합니다. 호출은 감사 로그에 남습니다.
    </p>
    <p v-else class="text-xs leading-relaxed text-muted-foreground">
      지원자 데이터가 없는 고정 문장 세 개(문장, 같은 약어를 쓴 비슷한 문장, 무관한 문장)를 임베딩해 차원과, 비슷한 문장이 더 가깝게 나오는지 확인합니다.
    </p>

    <div class="flex items-center gap-2">
      <Button size="sm" :disabled="!audioReady || run.isPending" data-testid="run-test" @click="run.mutate()">
        <component :is="run.data ? RotateCcwIcon : PlayIcon" />
        {{ run.isPending ? '테스트 중…' : run.data ? '다시 테스트' : '연결 테스트' }}
      </Button>
      <span v-if="run.isPending && (takesAudio(role) || takesDocument(role))" class="text-xs text-muted-foreground">로컬 모델은 처음 불러올 때 수십 초 걸릴 수 있습니다.</span>
    </div>

    <p v-if="run.isError" class="flex items-start gap-1.5 text-[13px] text-danger" role="alert">
      <CircleAlertIcon class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      {{ errorMessage(run.error) }}
    </p>

    <div v-if="result" class="space-y-3 rounded-lg border bg-card p-3.5" data-testid="test-result" :data-ok="result.ok">
      <div class="flex flex-wrap items-center gap-2">
        <Badge v-if="result.ok" variant="success"><CircleCheckIcon aria-hidden="true" />통과</Badge>
        <Badge v-else variant="danger"><CircleAlertIcon aria-hidden="true" />실패</Badge>
        <Badge v-if="str('failure')" variant="danger" data-testid="test-failure">{{ FAILURE_LABEL[str('failure')!] ?? str('failure') }}</Badge>
        <span class="text-[13px]">{{ result.summary }}</span>
      </div>
      <div class="flex flex-wrap gap-1.5 text-xs">
        <Badge variant="outline" class="font-mono">{{ result.model }}</Badge>
        <Badge v-if="str('server_model') && str('server_model') !== result.model" variant="outline" class="font-mono" data-testid="server-model">
          서버 보고 {{ str('server_model') }}
        </Badge>
        <Badge variant="outline" class="tabular">처리 {{ (result.latency_ms / 1000).toFixed(1) }}초</Badge>
        <Badge v-if="num('generate_ms') !== null" variant="outline" class="tabular">응답 {{ (num('generate_ms')! / 1000).toFixed(1) }}초</Badge>
        <Badge v-if="num('first_token_ms') !== null" variant="outline" class="tabular" data-testid="first-token">첫 토큰 {{ (num('first_token_ms')! / 1000).toFixed(1) }}초</Badge>
        <Badge v-if="num('audio_seconds') !== null" variant="outline" class="tabular">음성 {{ num('audio_seconds')!.toFixed(1) }}초</Badge>
        <Badge v-if="num('realtime_factor') !== null" variant="outline" class="tabular">음성 길이의 {{ num('realtime_factor')!.toFixed(2) }}배 시간</Badge>
        <Badge v-if="num('cer') !== null" variant="outline" class="tabular">CER {{ (num('cer')! * 100).toFixed(1) }}%</Badge>
        <Badge v-if="num('delay_ms') !== null" variant="outline" class="tabular" data-testid="denoise-delay">지연 {{ num('delay_ms') }}ms</Badge>
        <Badge v-if="num('cpu_ms_per_second') !== null" variant="outline" class="tabular">음성 1초당 {{ num('cpu_ms_per_second') }}ms</Badge>
        <Badge v-if="num('speech_change_db') !== null" variant="outline" class="tabular" data-testid="denoise-levels">
          말소리 {{ signed(num('speech_change_db')!) }}dB · 그 밖 {{ signed(num('other_change_db') ?? 0) }}dB
        </Badge>
        <Badge v-if="num('dimensions') !== null" variant="outline" class="tabular">{{ num('dimensions') }}차원</Badge>
        <Badge v-if="out.sparse === true" variant="outline">단어 일치 가중치 있음</Badge>
        <Badge v-if="num('similar') !== null" variant="outline" class="tabular" data-testid="embedding-similar">
          비슷한 문장 {{ num('similar')!.toFixed(2) }} · 무관한 문장 {{ num('unrelated')!.toFixed(2) }}
        </Badge>
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
      <p v-if="servedModels" class="text-xs text-muted-foreground" data-testid="server-models">
        서버가 가진 모델: <span class="font-mono">{{ servedModels.join(', ') || '없음' }}</span>
      </p>
      <template v-if="reading">
        <div class="flex flex-wrap gap-1.5 text-xs">
          <Badge v-if="reading.format" variant="outline" class="uppercase">{{ reading.format }}</Badge>
          <Badge v-if="result.document === 'upload'" variant="outline"><FileTextIcon aria-hidden="true" />올린 파일</Badge>
        </div>
        <div v-if="reading.pages?.length" class="overflow-x-auto rounded-md border">
          <table class="w-full text-left text-xs" data-testid="reading-pages">
            <thead class="bg-subtle text-muted-foreground">
              <tr>
                <th class="px-2.5 py-1.5 font-medium">쪽</th>
                <th class="px-2.5 py-1.5 font-medium">방식</th>
                <th class="px-2.5 py-1.5 font-medium">이유</th>
                <th class="px-2.5 py-1.5 font-medium">도구</th>
                <th class="px-2.5 py-1.5 font-medium">신뢰도</th>
                <th class="px-2.5 py-1.5 font-medium">시간</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in reading.pages" :key="p.page" class="border-t" :data-method="p.method">
                <td class="px-2.5 py-1.5 tabular">{{ p.page }}</td>
                <td class="px-2.5 py-1.5">
                  <Badge :variant="p.method === 'held' ? 'danger' : p.method === 'ocr' ? 'brand' : 'outline'">{{ READ_METHOD_LABEL[p.method] ?? p.method }}</Badge>
                </td>
                <td class="px-2.5 py-1.5 text-muted-foreground">{{ p.reason ?? '' }}</td>
                <td class="px-2.5 py-1.5 font-mono text-[11px]">{{ p.tool ?? '' }}</td>
                <td class="px-2.5 py-1.5 tabular">{{ p.method === 'ocr' ? percent(p.confidence) : '' }}</td>
                <td class="px-2.5 py-1.5 tabular">{{ p.method === 'ocr' ? seconds(p.elapsed_ms) : '' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <ul v-if="reading.images?.length" class="space-y-1 text-xs" data-testid="reading-images">
          <li v-for="i in reading.images" :key="i.label" class="flex flex-wrap items-center gap-1.5">
            <span class="font-medium">{{ i.label }}</span>
            <Badge :variant="i.decision === 'photo' ? 'warning' : i.decision === 'ocr' ? 'brand' : 'outline'">{{ PICTURE_LABEL[i.decision] ?? i.decision }}</Badge>
            <span class="text-muted-foreground">{{ i.detail }}</span>
          </li>
        </ul>
        <p v-if="reading.tools?.length" class="text-xs text-muted-foreground">
          쓴 도구: <span class="font-mono">{{ reading.tools.join(' · ') }}</span>
        </p>
        <div v-if="reading.preview" class="space-y-1.5">
          <p class="text-xs font-medium text-muted-foreground">비식별화된 미리보기 (LLM에 가는 형태, 원문은 보여 주지 않습니다)</p>
          <pre class="max-h-64 overflow-auto rounded-md bg-subtle px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap" data-testid="reading-preview">{{ reading.preview }}{{ reading.preview_truncated ? ' …' : '' }}</pre>
        </div>
        <ul v-if="reading.warnings?.length" class="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
          <li v-for="w in reading.warnings" :key="w">{{ w }}</li>
        </ul>
      </template>
      <p v-if="result.error" class="text-xs text-danger">{{ result.error }}</p>
    </div>
  </div>
</template>
