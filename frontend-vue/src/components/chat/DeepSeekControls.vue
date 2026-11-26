<script setup lang="ts">
import { ref } from 'vue'
import { checkDeepSeekKey } from '@/api/chat'

const key = defineModel<string>({ required: true })
const draft = ref('')
const expanded = ref(false)
const checking = ref(false)
const message = ref('')

async function connect(): Promise<void> {
  const candidate = draft.value.trim()
  if (!candidate || checking.value) return
  checking.value = true
  message.value = ''
  try {
    await checkDeepSeekKey(candidate)
    key.value = candidate
    draft.value = ''
    message.value = '已验证，接下来的回答将使用 DeepSeek。'
  } catch (error) {
    message.value = error instanceof Error ? error.message : 'DeepSeek 连接失败。'
  } finally {
    checking.value = false
  }
}

function disconnect(): void {
  key.value = ''
  draft.value = ''
  message.value = '已恢复本地模式。'
}
</script>

<template>
  <div class="flex-shrink-0 border-b border-border px-4 py-2 text-chat-ui">
    <div class="chat-container space-y-2">
      <button type="button" class="font-medium text-primary" :aria-expanded="expanded" @click="expanded = !expanded">
        回答模型 · {{ key ? 'DeepSeek' : '本地' }}
      </button>
      <form v-if="expanded" class="space-y-2" @submit.prevent="connect">
        <label for="deepseek-key" class="block font-medium">DeepSeek API Key</label>
        <div class="flex flex-wrap items-center gap-3">
          <input
            id="deepseek-key" v-model="draft" type="password" autocomplete="off" maxlength="256"
            :disabled="checking" class="min-w-56 rounded border border-border bg-background px-2 py-1"
          >
          <button type="submit" class="text-primary disabled:text-muted-foreground" :disabled="checking || !draft.trim()">
            {{ checking ? '正在验证…' : '验证并使用' }}
          </button>
          <button v-if="key" type="button" :disabled="checking" @click="disconnect">恢复本地模式</button>
        </div>
        <p class="text-chat-caption text-muted-foreground">Key 仅在此页面有效。启用后，问题和回答所需的上下文会发送给 DeepSeek。</p>
        <p v-if="message" role="status">{{ message }}</p>
      </form>
    </div>
  </div>
</template>
