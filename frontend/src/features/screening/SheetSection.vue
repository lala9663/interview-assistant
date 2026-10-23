<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{ title: string; icon?: Component }>()
</script>

<template>
  <section class="space-y-2.5">
    <h3 class="flex items-center gap-1.5 text-[13px] font-semibold">
      <component :is="icon" v-if="icon" class="size-4 text-muted-foreground" aria-hidden="true" />
      {{ title }}
    </h3>
    <slot />
  </section>
</template>
