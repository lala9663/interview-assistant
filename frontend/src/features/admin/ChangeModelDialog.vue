<script setup lang="ts">
import { ArrowLeftIcon, ArrowRightIcon, CircleAlertIcon, TriangleAlertIcon } from '@lucide/vue'
import { useMutation } from '@tanstack/vue-query'
import { computed, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { endpoints } from '@/api/endpoints'
import { useApplyModel } from '@/api/queries'
import type { ModelImpl, ModelOptionValue, ModelRoleState, ModelTestResult } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { errorMessage, toastError } from '@/lib/toast'
import { cn } from '@/lib/utils'

import DataLocationBadge from './DataLocationBadge.vue'
import { initialOptions } from './labels'
import ModelOptionsForm from './ModelOptionsForm.vue'
import ModelTestPanel from './ModelTestPanel.vue'
import RequirementList from './RequirementList.vue'

/**
 * 변경 다이얼로그: provider → 모델·옵션 → 요구 조건 → (외부 전송 경고) → 연결 테스트 → 사유 → 적용.
 * Applying swaps the provider for new work without a restart; interviews in progress keep theirs.
 */
const props = defineProps<{ open: boolean; state: ModelRoleState | null; catalog: ModelImpl[] }>()
const emit = defineEmits<{ close: [] }>()

type Step = 'provider' | 'options' | 'check' | 'external' | 'test' | 'apply'
const STEP_LABEL: Record<Step, string> = {
  provider: 'Provider',
  options: '모델·옵션',
  check: '요구 조건',
  external: '외부 전송',
  test: '연결 테스트',
  apply: '사유·적용',
}

const implKey = ref('')
const options = ref<Record<string, ModelOptionValue>>({})
const step = ref<Step>('provider')
const confirmExternal = ref(false)
const reason = ref('')
const testResult = ref<ModelTestResult | null>(null)

const role = computed(() => props.state?.role ?? 'llm.primary')
const impls = computed(() => props.catalog.filter((i) => i.roles.includes(role.value)))
const impl = computed(() => impls.value.find((i) => i.impl === implKey.value) ?? null)
const external = computed(() => impl.value?.data_location === 'external')
const steps = computed<Step[]>(() => ['provider', 'options', 'check', ...(external.value ? (['external'] as Step[]) : []), 'test', 'apply'])
const index = computed(() => steps.value.indexOf(step.value))

const check = reactive(
  useMutation({ mutationFn: () => endpoints.checkModel(role.value, { impl: implKey.value, options: options.value }) }),
)
const apply = useApplyModel()
const spec = computed(() => check.data?.spec ?? { impl: implKey.value, options: options.value })

function reset() {
  const current = props.state?.spec ?? null
  implKey.value = current?.impl ?? impls.value[0]?.impl ?? ''
  const first = impls.value.find((i) => i.impl === implKey.value)
  options.value = first ? initialOptions(first, role.value, current) : {}
  step.value = 'provider'
  confirmExternal.value = false
  reason.value = ''
  testResult.value = null
  check.reset()
}

watch(
  () => props.open,
  (o) => o && reset(),
  { immediate: true },
)

function chooseImpl(next: ModelImpl) {
  if (next.impl === implKey.value) return
  implKey.value = next.impl
  options.value = initialOptions(next, role.value, props.state?.spec ?? null)
  confirmExternal.value = false
}

// Changing the provider or its options invalidates the check and the test.
watch([implKey, options], () => {
  check.reset()
  testResult.value = null
})

const machineUnmet = (i: ModelImpl) => i.requirements.filter((r) => !r.ok)

const canNext = computed(() => {
  switch (step.value) {
    case 'provider':
      return impl.value !== null
    case 'options':
      return true
    case 'check':
      return Boolean(check.data?.ready && !check.data.same_as_active)
    case 'external':
      return confirmExternal.value
    case 'test':
      return Boolean(testResult.value?.ok)
    default:
      return false
  }
})

function go(next: Step) {
  step.value = next
  if (next === 'check') check.mutate()
}

const next = () => canNext.value && go(steps.value[index.value + 1]!)
const back = () => index.value > 0 && go(steps.value[index.value - 1]!)

function close() {
  if (apply.isPending) return
  emit('close')
}

function submit() {
  if (!reason.value.trim() || !props.state) return
  apply.mutate(
    { role: role.value, body: { ...spec.value, reason: reason.value.trim(), confirm_external: confirmExternal.value } },
    {
      onSuccess: (s) => {
        toast.success(`${s.label}: ${s.model}로 바꿨습니다`, { description: '재시작 없이 적용했습니다. 새로 시작하는 면접부터 이 모델을 씁니다.' })
        emit('close')
      },
      onError: toastError('적용하지 못했습니다'),
    },
  )
}

const optionSummary = computed(() =>
  Object.entries(spec.value.options)
    .filter(([k, v]) => k !== 'language' && v !== '' && v !== null)
    .map(([k, v]) => `${k}=${typeof v === 'string' && v.length > 24 ? `${v.slice(0, 24)}…` : v}`)
    .join(', '),
)
</script>

<template>
  <Dialog :open="open" @update:open="(o) => !o && close()">
    <DialogContent class="max-w-2xl">
      <DialogHeader>
        <DialogTitle>{{ state?.label }} 변경</DialogTitle>
        <DialogDescription>지금: {{ state?.impl_label }} · <span class="font-mono">{{ state?.model }}</span></DialogDescription>
      </DialogHeader>

      <ol class="flex flex-wrap items-center gap-1.5 text-xs" aria-label="단계">
        <li
          v-for="(s, i) in steps"
          :key="s"
          :aria-current="s === step ? 'step' : undefined"
          :class="
            cn(
              'flex items-center gap-1.5 rounded-full border px-2.5 py-1',
              s === step ? 'border-brand-border bg-brand-soft font-medium text-brand' : i < index ? 'text-foreground' : 'text-muted-foreground',
              s === 'external' && 'border-[color-mix(in_oklch,var(--warning)_40%,transparent)]',
            )
          "
        >
          <span class="tabular">{{ i + 1 }}</span>
          {{ STEP_LABEL[s] }}
        </li>
      </ol>

      <!-- 1. provider -->
      <div v-if="step === 'provider'" role="radiogroup" aria-label="Provider" class="space-y-2">
        <div
          v-for="i in impls"
          :key="i.impl"
          role="radio"
          tabindex="0"
          :aria-checked="i.impl === implKey"
          :data-testid="`impl-${i.impl}`"
          :class="
            cn(
              'cursor-pointer rounded-lg border bg-card p-3 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50',
              i.impl === implKey && 'border-brand-border bg-brand-soft hover:bg-brand-soft',
            )
          "
          @click="chooseImpl(i)"
          @keydown.enter.prevent="chooseImpl(i)"
          @keydown.space.prevent="chooseImpl(i)"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-medium">{{ i.label }}</span>
            <DataLocationBadge :location="i.data_location" />
            <Badge v-if="state?.spec.impl === i.impl" variant="outline">사용 중</Badge>
            <span class="ml-auto text-[11px] text-muted-foreground">{{ i.license }}</span>
          </div>
          <p class="mt-1 text-xs leading-relaxed text-muted-foreground">{{ i.description }}</p>
          <p class="mt-1 text-xs text-muted-foreground">{{ i.data_note }}</p>
          <div v-if="machineUnmet(i).length" class="mt-1.5 flex flex-wrap gap-1">
            <Badge v-for="r in machineUnmet(i)" :key="r.key" variant="danger">{{ r.label }}: {{ r.detail }}</Badge>
          </div>
        </div>
      </div>

      <!-- 2. options -->
      <div v-else-if="step === 'options' && impl" class="space-y-3">
        <p v-if="impl.role_notes[role]" class="rounded-lg border bg-subtle px-3 py-2 text-xs leading-relaxed text-muted-foreground">{{ impl.role_notes[role] }}</p>
        <ModelOptionsForm v-model="options" :impl="impl" :role="role" />
      </div>

      <!-- 3. requirements -->
      <div v-else-if="step === 'check'" class="space-y-3">
        <p v-if="check.isPending" class="text-sm text-muted-foreground">확인하는 중…</p>
        <p v-else-if="check.isError" class="flex items-start gap-1.5 text-[13px] text-danger" role="alert">
          <CircleAlertIcon class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {{ errorMessage(check.error) }} (이전 단계에서 고칠 수 있습니다)
        </p>
        <template v-else-if="check.data">
          <RequirementList :requirements="check.data.requirements" />
          <p v-if="check.data.same_as_active" class="text-[13px] text-muted-foreground">지금 쓰는 설정과 같습니다. 바꿀 것이 없습니다.</p>
          <p v-else-if="!check.data.ready" class="text-[13px] text-danger">요구 조건을 모두 충족해야 테스트하고 적용할 수 있습니다.</p>
          <p class="text-xs text-muted-foreground">API 키·자격증명은 화면에서 받지 않습니다. 서버 환경변수나 Secret Manager로 넣고, 여기에는 있음/없음만 보입니다.</p>
        </template>
      </div>

      <!-- 4. external warning -->
      <div v-else-if="step === 'external'" class="space-y-3" data-testid="external-warning">
        <div class="flex items-start gap-2.5 rounded-lg border border-[color-mix(in_oklch,var(--warning)_40%,transparent)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] p-3.5">
          <TriangleAlertIcon class="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          <div class="space-y-1.5 text-[13px] leading-relaxed">
            <p class="font-medium">회사 밖 API로 데이터를 보내는 provider입니다.</p>
            <p class="text-muted-foreground">{{ impl?.data_note }}</p>
            <p class="text-muted-foreground">
              LLM 입력은 바꾼 뒤에도 비식별화를 거치지만, 비식별 텍스트(또는 음성)가 이 PC와 사내 GCP 밖으로 나갑니다. 연결 테스트도 외부로
              요청을 보냅니다. 보안 담당 확인이 필요하면 적용하지 마세요.
            </p>
          </div>
        </div>
        <label class="flex items-center gap-2 text-[13px]">
          <Checkbox v-model="confirmExternal" />
          외부 전송을 확인했습니다. 테스트와 적용에 사유와 함께 기록됩니다.
        </label>
      </div>

      <!-- 6. reason + apply -->
      <div v-else-if="step === 'apply'" class="space-y-4">
        <dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-lg border bg-subtle px-3.5 py-3 text-[13px]">
          <dt class="text-muted-foreground">지금</dt>
          <dd>{{ state?.impl_label }} · <span class="font-mono">{{ state?.model }}</span></dd>
          <dt class="text-muted-foreground">바꿀 것</dt>
          <dd>
            {{ impl?.label }} · <span class="font-mono">{{ testResult?.model }}</span>
            <span v-if="optionSummary" class="block text-xs text-muted-foreground">{{ optionSummary }}</span>
          </dd>
          <dt class="text-muted-foreground">데이터 위치</dt>
          <dd><DataLocationBadge v-if="impl" :location="impl.data_location" /></dd>
        </dl>
        <div class="space-y-1.5">
          <Label for="change-reason">변경 사유</Label>
          <Textarea id="change-reason" v-model="reason" rows="2" :maxlength="500" placeholder="예: 사후 전사 정확도 개선을 위해 로컬 Whisper large-v3로 교체" />
          <p class="text-xs text-muted-foreground">이력과 감사 로그에 이름과 함께 남습니다. 재시작 없이 바로 적용되고, 진행 중인 면접은 시작할 때의 모델을 끝까지 씁니다.</p>
        </div>
      </div>

      <!-- 5. test: kept mounted so its result survives going back from step 6 -->
      <div v-show="step === 'test'" class="space-y-3">
        <ModelTestPanel :role="role" :spec="spec" :confirm-external="confirmExternal" @result="(r) => (testResult = r)" />
      </div>

      <DialogFooter class="sm:justify-between">
        <Button variant="ghost" :disabled="index === 0 || apply.isPending" @click="back">
          <ArrowLeftIcon />
          이전
        </Button>
        <div class="flex gap-2">
          <Button variant="outline" :disabled="apply.isPending" @click="close">취소</Button>
          <Button v-if="step !== 'apply'" :disabled="!canNext" @click="next">
            다음
            <ArrowRightIcon />
          </Button>
          <Button v-else :disabled="!reason.trim() || apply.isPending" data-testid="apply" @click="submit">
            {{ apply.isPending ? '적용 중…' : '적용' }}
          </Button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
