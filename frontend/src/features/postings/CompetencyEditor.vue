<script setup lang="ts">
import { PlusIcon, Trash2Icon } from '@lucide/vue'

import { BARS_LEVELS, type BarsLevel, type Competency } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

import { emptyCompetency, LEVEL_HINT } from './competency-utils'

/** Editable rubric for draft versions. Every change emits a new array (the draft is never mutated in place). */
const model = defineModel<Competency[]>({ required: true })

const patch = (i: number, c: Competency) => (model.value = model.value.map((x, j) => (j === i ? c : x)))
const setBar = (i: number, c: Competency, l: BarsLevel, v: string) => patch(i, { ...c, bars: { ...c.bars, [l]: v } })
</script>

<template>
  <div class="space-y-3">
    <div v-for="(c, i) in model" :key="i" class="rounded-xl border bg-card p-4">
      <div class="grid gap-3 md:grid-cols-[220px_1fr_auto] md:items-end">
        <div class="space-y-1.5">
          <Label :for="`cname-${i}`">역량 이름</Label>
          <Input :id="`cname-${i}`" :model-value="c.name" placeholder="예: 공정 문제 해결" @update:model-value="(v) => patch(i, { ...c, name: v })" />
        </div>
        <div class="space-y-1.5">
          <Label :for="`cdesc-${i}`">정의</Label>
          <Input
            :id="`cdesc-${i}`"
            :model-value="c.description"
            placeholder="관찰 가능한 행동으로 정의"
            @update:model-value="(v) => patch(i, { ...c, description: v })"
          />
        </div>
        <Button variant="ghost" size="icon-sm" :aria-label="`${c.name || '역량'} 삭제`" @click="model = model.filter((_, j) => j !== i)">
          <Trash2Icon />
        </Button>
      </div>
      <div class="mt-3 grid gap-2 md:grid-cols-5">
        <div v-for="l in BARS_LEVELS" :key="l" class="space-y-1">
          <Label :for="`bars-${i}-${l}`" class="text-xs text-muted-foreground">{{ l }}점 · {{ LEVEL_HINT[l] }}</Label>
          <Textarea
            :id="`bars-${i}-${l}`"
            :model-value="c.bars[l]"
            class="min-h-24 text-[12.5px]"
            :aria-invalid="c.bars[l].trim() === ''"
            @update:model-value="(v) => setBar(i, c, l, v)"
          />
        </div>
      </div>
    </div>
    <Button variant="outline" size="sm" @click="model = [...model, emptyCompetency()]">
      <PlusIcon />
      역량 추가
    </Button>
  </div>
</template>
