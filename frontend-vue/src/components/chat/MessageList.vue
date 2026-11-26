<script setup lang="ts">
import { MessageCircle } from 'lucide-vue-next'
import type { DisplayMessage, StreamingMessage } from '@/api/types'
import MessageBubble from './MessageBubble.vue'

defineProps<{
  messages: DisplayMessage[]
  streamingMessage?: StreamingMessage | null
}>()

defineEmits<{
  'prompt-selected': [prompt: string]
}>()

const samplePrompts = ['图书馆电子资源怎么在校外访问？', '北邮本科选课从哪里进？', '新生报到通知在哪里看？', '毕业去向信息怎么审核？']
</script>

<template>
  <div
    role="log"
    aria-label="Conversation"
    aria-live="polite"
    aria-relevant="additions"
    class="py-4 flex flex-col"
    :class="{ 'min-h-full': messages.length === 0 && !streamingMessage }"
  >
    <ul role="list" class="flex flex-col">
      <li
        v-if="messages.length === 0 && !streamingMessage"
        class="flex items-center justify-center flex-1 py-12 sm:py-16 list-none"
      >
        <div class="text-center space-y-5 max-w-lg mx-auto px-4">
          <div class="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary mx-auto">
            <MessageCircle class="h-7 w-7" aria-hidden="true" />
          </div>
          <div>
            <h2 class="text-chat-display text-foreground">北邮校园指南</h2>
            <p class="text-muted-foreground text-chat-body mt-2">
              查询教务、科研、校园生活和学生服务，点击回答下方的来源核对官网原文。
            </p>
          </div>
          <div class="grid grid-cols-1 gap-2 text-left">
            <p class="text-chat-label text-muted-foreground">试试这些问题</p>
            <button
              v-for="prompt in samplePrompts"
              :key="prompt"
              type="button"
              class="text-chat-ui text-left p-3 rounded-lg border border-border hover:bg-accent hover:text-accent-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              @click="$emit('prompt-selected', prompt)"
            >
              {{ prompt }}
            </button>
          </div>
        </div>
      </li>

      <li
        v-for="(message, index) in messages"
        :key="String(message.id)"
        class="list-none w-full"
      >
        <MessageBubble
          :message="message"
          :is-last-message="index === messages.length - 1 && !streamingMessage"
        />
      </li>

      <li v-if="streamingMessage" class="list-none w-full">
        <MessageBubble :message="streamingMessage" :is-streaming="true" />
      </li>
    </ul>
  </div>
</template>
