<script setup lang="ts">
import { ref, watch } from 'vue'

import { Sheet, SheetContent } from '@/components/ui/sheet'

import ApplicationDetail from './ApplicationDetail.vue'

const props = defineProps<{ applicationId: string | null; postingId: string }>()
const emit = defineEmits<{ close: [] }>()

// Keep the last application on screen while the sheet slides out.
const shownId = ref(props.applicationId)
watch(
  () => props.applicationId,
  (id) => {
    if (id) shownId.value = id
  },
)
</script>

<template>
  <Sheet :open="applicationId !== null" @update:open="(o) => !o && emit('close')">
    <SheetContent class="overflow-y-auto scrollbar-thin">
      <ApplicationDetail v-if="shownId" :key="shownId" :application-id="shownId" :posting-id="postingId" />
    </SheetContent>
  </Sheet>
</template>
