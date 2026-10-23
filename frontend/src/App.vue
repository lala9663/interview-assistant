<script setup lang="ts">
import { RouterView } from 'vue-router'
import { Toaster } from 'vue-sonner'

import { TooltipProvider } from '@/components/ui/tooltip'
import { useTheme } from '@/lib/theme'

const { resolved } = useTheme()
</script>

<template>
  <TooltipProvider :delay-duration="250">
    <RouterView />
    <Toaster
      :theme="resolved"
      position="bottom-right"
      :toast-options="{ classes: { toast: 'font-sans !rounded-lg !border !shadow-xl', description: '!text-muted-foreground' } }"
    />
  </TooltipProvider>
</template>
