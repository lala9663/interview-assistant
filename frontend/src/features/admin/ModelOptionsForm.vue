<script setup lang="ts">
import { CircleCheckIcon, DownloadIcon, LockIcon, XIcon } from '@lucide/vue'
import { computed } from 'vue'

import { useModelDownloadMutations, useModelDownloads } from '@/api/queries'
import type { ModelDownload, ModelImpl, ModelOptionChoice, ModelOptionField, ModelOptionValue } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { toastError } from '@/lib/toast'
import { cn } from '@/lib/utils'

import { fieldsFor, formatBytes, ROLE_SHORT, weightsField } from './labels'

/**
 * Options of one provider for one role, drawn from the catalog's schema. A model choice that needs
 * weights shows its size and a download button; a model can be applied only once it is downloaded.
 */
const props = defineProps<{ impl: ModelImpl; role: string }>()
const values = defineModel<Record<string, ModelOptionValue>>({ required: true })

const fields = computed(() => fieldsFor(props.impl, props.role))
const weights = computed(() => weightsField(props.impl))
const kind = computed(() => props.impl.kind)
const staysHere = computed(() => (kind.value === 'stt' ? '음성은' : kind.value === 'embedding' ? '질문·답변 텍스트는' : '서류와 그림은'))
const downloads = useModelDownloads(() => Boolean(weights.value))
const mutations = useModelDownloadMutations()

function set(key: string, v: ModelOptionValue) {
  values.value = { ...values.value, [key]: v }
}

function download(choice: ModelOptionChoice): ModelDownload | undefined {
  return downloads.data?.find((d) => d.impl === props.impl.impl && d.model === choice.value)
}

function isDownloaded(choice: ModelOptionChoice) {
  const d = download(choice)
  return d ? d.status === 'done' : Boolean(choice.downloaded)
}

function percent(d: ModelDownload) {
  return d.total_bytes ? Math.min(100, Math.round((d.downloaded_bytes / d.total_bytes) * 100)) : 0
}

const startDownload = (choice: ModelOptionChoice) =>
  mutations.start.mutate({ impl: props.impl.impl, model: choice.value }, { onError: toastError('다운로드를 시작하지 못했습니다') })
const cancelDownload = (choice: ModelOptionChoice) => mutations.cancel.mutate({ impl: props.impl.impl, model: choice.value })

const inputId = (f: ModelOptionField) => `opt-${props.role}-${f.key}`
const numberValue = (f: ModelOptionField) => (typeof values.value[f.key] === 'number' ? String(values.value[f.key]) : '')
</script>

<template>
  <div class="space-y-5">
    <div v-for="f in fields" :key="f.key" class="space-y-1.5">
      <template v-if="weights && f.key === weights.key">
        <p class="text-[13px] font-medium">{{ f.label }}</p>
        <div role="radiogroup" :aria-label="f.label" class="grid gap-2 sm:grid-cols-2">
          <div
            v-for="c in f.choices"
            :key="c.value"
            role="radio"
            tabindex="0"
            :aria-checked="values[f.key] === c.value"
            :data-testid="`model-choice-${c.value}`"
            :class="
              cn(
                'cursor-pointer rounded-lg border bg-card p-3 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50',
                values[f.key] === c.value && 'border-brand-border bg-brand-soft hover:bg-brand-soft',
              )
            "
            @click="set(f.key, c.value)"
            @keydown.enter.prevent="set(f.key, c.value)"
            @keydown.space.prevent="set(f.key, c.value)"
          >
            <div class="flex items-center gap-1.5">
              <span class="font-mono text-[13px] font-semibold">{{ c.label }}</span>
              <Badge v-if="c.recommended_for.includes(role)" variant="brand">{{ ROLE_SHORT[role] ?? '' }} 권장</Badge>
              <span class="ml-auto text-xs text-muted-foreground tabular">{{ formatBytes(c.size_bytes) }}</span>
            </div>
            <p class="mt-1 text-xs leading-relaxed text-muted-foreground">{{ c.note }}</p>
            <div class="mt-2 flex items-center gap-2 text-xs" @click.stop>
              <template v-if="isDownloaded(c)">
                <CircleCheckIcon class="size-3.5 text-success" aria-hidden="true" />
                <span class="text-success">내려받음</span>
              </template>
              <template v-else-if="download(c)?.status === 'downloading'">
                <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar" :aria-valuenow="percent(download(c)!)" aria-valuemin="0" aria-valuemax="100" :aria-label="`${c.label} 다운로드`">
                  <div class="h-full rounded-full bg-primary transition-[width]" :style="{ width: `${percent(download(c)!)}%` }"></div>
                </div>
                <span class="tabular">{{ percent(download(c)!) }}%</span>
                <Button size="icon-xs" variant="ghost" :aria-label="`${c.label} 다운로드 취소`" @click="cancelDownload(c)"><XIcon /></Button>
              </template>
              <template v-else>
                <Button size="xs" variant="outline" :disabled="mutations.start.isPending" @click="startDownload(c)">
                  <DownloadIcon />
                  다운로드 {{ formatBytes(c.size_bytes) }}
                </Button>
                <span v-if="download(c)?.status === 'failed'" class="truncate text-danger" :title="download(c)?.error ?? ''">실패: 다시 시도</span>
              </template>
            </div>
          </div>
        </div>
        <p class="text-xs text-muted-foreground">
          모델 파일은 관리자가 내려받기를 누를 때 한 번만 받습니다({{ impl.impl === 'tesseract' ? 'GitHub' : 'Hugging Face' }}, 커밋 고정, 해시 검증).
          {{ staysHere }} 이 PC 밖으로 나가지 않습니다.
        </p>
      </template>

      <template v-else-if="f.fixed">
        <p class="text-[13px] font-medium">{{ f.label }}</p>
        <p class="flex items-center gap-1.5 text-sm text-muted-foreground">
          <LockIcon class="size-3.5" aria-hidden="true" />
          {{ values[f.key] ?? f.default }}
          <span class="text-xs">· {{ f.help }}</span>
        </p>
      </template>

      <template v-else-if="f.type === 'select'">
        <Label :for="inputId(f)">{{ f.label }}</Label>
        <Select :model-value="String(values[f.key] ?? '')" @update:model-value="(v) => set(f.key, String(v))">
          <SelectTrigger :id="inputId(f)" class="max-w-sm"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem v-for="c in f.choices" :key="c.value" :value="c.value">
              {{ c.label }}<span v-if="c.note" class="text-muted-foreground"> · {{ c.note }}</span>
            </SelectItem>
          </SelectContent>
        </Select>
      </template>

      <template v-else-if="f.type === 'boolean'">
        <div class="flex items-center gap-2">
          <Switch :id="inputId(f)" :model-value="Boolean(values[f.key])" @update:model-value="(v: boolean) => set(f.key, v)" />
          <Label :for="inputId(f)">{{ f.label }}</Label>
        </div>
      </template>

      <template v-else-if="f.type === 'text'">
        <Label :for="inputId(f)">{{ f.label }}</Label>
        <Textarea
          :id="inputId(f)"
          :model-value="String(values[f.key] ?? '')"
          :maxlength="f.max_length"
          rows="2"
          @update:model-value="(v: string) => set(f.key, v)"
        />
      </template>

      <template v-else-if="f.type === 'integer' || f.type === 'number'">
        <Label :for="inputId(f)">{{ f.label }}</Label>
        <Input
          :id="inputId(f)"
          type="number"
          class="max-w-40"
          :min="f.minimum ?? undefined"
          :max="f.maximum ?? undefined"
          :step="f.type === 'integer' ? 1 : 0.1"
          :model-value="numberValue(f)"
          @update:model-value="(v) => v !== '' && set(f.key, Number(v))"
        />
      </template>

      <template v-else>
        <Label :for="inputId(f)">{{ f.label }}</Label>
        <Input :id="inputId(f)" class="max-w-sm" :model-value="String(values[f.key] ?? '')" @update:model-value="(v) => set(f.key, String(v))" />
      </template>

      <p v-if="f.help && !f.fixed" class="text-xs leading-relaxed text-muted-foreground">{{ f.help }}</p>
    </div>
    <p v-if="fields.length === 0" class="text-sm text-muted-foreground">이 provider는 고를 옵션이 없습니다.</p>
  </div>
</template>
