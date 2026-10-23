<script setup lang="ts">
import type { CandidateNote, QAItem, SessionInterviewerView } from '@/api/types'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import NotesPanel from './NotesPanel.vue'
import QaLog from './QaLog.vue'

defineProps<{
  qaItems: QAItem[]
  editedIds: ReadonlySet<string>
  answeringId: string | null
  notes: CandidateNote[]
  panel: SessionInterviewerView[]
  saveNote: (content: string) => Promise<boolean>
  notePending: boolean
}>()
</script>

<template>
  <Tabs default-value="qa" class="flex min-h-0 flex-1 flex-col">
    <TabsList class="w-full">
      <TabsTrigger value="qa" class="flex-1">
        Q&A 기록 <span class="text-muted-foreground tabular">{{ qaItems.length }}</span>
      </TabsTrigger>
      <TabsTrigger value="notes" class="flex-1">
        메모 <span class="text-muted-foreground tabular">{{ notes.length }}</span>
      </TabsTrigger>
    </TabsList>
    <TabsContent value="qa" class="mt-3 min-h-0 flex-1">
      <QaLog :qa-items="qaItems" :edited-ids="editedIds" :answering-id="answeringId" />
    </TabsContent>
    <TabsContent value="notes" class="mt-3 min-h-0 flex-1">
      <NotesPanel :notes="notes" :panel="panel" :save="saveNote" :pending="notePending" />
    </TabsContent>
  </Tabs>
</template>
