<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'

import { splitTokens } from '@/lib/labels'

import DeidToken from './DeidToken.vue'

/** Text with de-identification tokens rendered as chips. */
const props = defineProps<{ text: string; class?: HTMLAttributes['class'] }>()
const parts = computed(() => splitTokens(props.text))
</script>

<template>
  <span :class="props.class"
    ><template v-for="(part, i) in parts" :key="i"><DeidToken v-if="part.token" :token="part.text" /><template v-else>{{ part.text }}</template></template
  ></span>
</template>
