import { VueQueryPlugin } from '@tanstack/vue-query'
import { createApp } from 'vue'
import { createWebHistory } from 'vue-router'

import App from './App.vue'
import { createQueryClient } from './lib/query-client'
import { initTheme } from './lib/theme'
import { createAppRouter } from './router'
import 'vue-sonner/style.css'
import './index.css'

/** VITE_USE_MOCKS=true: every /api request is answered by MSW in the browser (no backend needed). */
async function enableMocking() {
  if (import.meta.env.VITE_USE_MOCKS !== 'true') return
  const { worker } = await import('./mocks/browser')
  await worker.start({ onUnhandledFrame: 'bypass', quiet: true })
}

void enableMocking().then(() => {
  initTheme()
  createApp(App)
    .use(createAppRouter(createWebHistory()))
    .use(VueQueryPlugin, { queryClient: createQueryClient() })
    .mount('#app')
})
