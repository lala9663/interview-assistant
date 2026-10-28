<script setup lang="ts">
import { computed } from 'vue'

import type { Interviewer, SessionMode } from '@/api/types'
import { Label } from '@/components/ui/label'
import { Segmented, SegmentedItem } from '@/components/ui/segmented'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

import { leadOf } from './booking'

/** 방식 and 주관 면접관 of a booking. The lead shown is leadOf(panel, lead), the one booked. */
const props = defineProps<{ panel: Interviewer[] }>()
const mode = defineModel<SessionMode>('mode', { required: true })
const lead = defineModel<string>('lead', { required: true })
const leadId = computed(() => leadOf(props.panel, lead.value))
</script>

<template>
  <div class="flex flex-wrap gap-6">
    <div class="space-y-1.5">
      <Label>방식</Label>
      <Segmented :model-value="mode" aria-label="면접 방식" @update:model-value="(v) => (mode = v as SessionMode)">
        <SegmentedItem value="remote">비대면</SegmentedItem>
        <SegmentedItem value="onsite">대면</SegmentedItem>
      </Segmented>
    </div>
    <div class="min-w-48 flex-1 space-y-1.5">
      <Label>주관 면접관</Label>
      <Select :model-value="leadId" :disabled="panel.length === 0" @update:model-value="(v) => (lead = typeof v === 'string' ? v : '')">
        <SelectTrigger aria-label="주관 면접관">
          <SelectValue placeholder="면접관을 먼저 고르세요" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="i in panel" :key="i.id" :value="i.id">{{ i.name }}</SelectItem>
        </SelectContent>
      </Select>
    </div>
  </div>
</template>
