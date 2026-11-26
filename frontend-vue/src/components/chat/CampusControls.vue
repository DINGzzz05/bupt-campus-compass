<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import client from '@/api/client'

const props = defineProps<{ sessionId: number }>()

interface SupportTask {
  task_id: string
  status: 'queued' | 'running' | 'completed' | 'needs_review'
  attempts: number
  receipt: string | null
}
interface MemoryState {
  revision: number
  facts: Record<string, string>
}

const labels: Record<SupportTask['status'], string> = {
  queued: '排队中', running: '处理中', completed: '已生成本地回执', needs_review: '等待人工重试',
}
const panel = ref<'support' | 'memory' | null>(null)
const summary = ref('')
const preview = ref<{ confirmation: string; summary: string } | null>(null)
const tasks = ref<SupportTask[]>([])
const memory = ref<MemoryState>({ revision: 0, facts: {} })
const factKey = ref('')
const factValue = ref('')
const busy = ref(false)
const message = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let mounted = true

const endpoint = (): string => `/api/bupt/sessions/${props.sessionId}`

async function refreshTasks(): Promise<void> {
  clearTimeout(timer)
  tasks.value = (await client.get<SupportTask[]>(`${endpoint()}/support`)).data
  if (mounted && panel.value === 'support' && tasks.value.some((task) => ['queued', 'running'].includes(task.status))) {
    timer = setTimeout(() => void refreshTasks().catch(() => {
      message.value = '暂时无法刷新任务状态。'
    }), 1200)
  }
}

async function perform(action: () => Promise<void>): Promise<void> {
  if (busy.value) return
  busy.value = true
  message.value = ''
  try {
    await action()
  } catch (err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
    message.value = typeof detail === 'string' ? detail : '操作未完成，请重试。'
  } finally {
    busy.value = false
  }
}

function toggle(next: 'support' | 'memory'): void {
  clearTimeout(timer)
  panel.value = panel.value === next ? null : next
  if (panel.value === 'support') void perform(refreshTasks)
  if (panel.value === 'memory') void perform(async () => {
    memory.value = (await client.get<MemoryState>(`${endpoint()}/memory`)).data
  })
}

function draft(): Promise<void> {
  return perform(async () => {
    preview.value = (await client.post(`${endpoint()}/support/draft`, { summary: summary.value })).data
  })
}

function confirm(): Promise<void> {
  return perform(async () => {
    if (!preview.value) return
    await client.post(`${endpoint()}/support/confirm`, { confirmation: preview.value.confirmation, confirmed: true })
    preview.value = null
    summary.value = ''
    await refreshTasks()
  })
}

function retry(task: SupportTask): Promise<void> {
  return perform(async () => {
    await client.post(`${endpoint()}/support/${task.task_id}/retry`)
    await refreshTasks()
  })
}

function change(operation: 'confirm' | 'correct' | 'forget' | 'clear'): void {
  if (operation === 'clear' && !window.confirm('清空当前会话的模型记忆并保留历史聊天记录？')) return
  void perform(async () => {
    memory.value = (await client.post<MemoryState>(`${endpoint()}/memory`, {
      operation,
      key: operation === 'clear' ? undefined : factKey.value,
      value: ['confirm', 'correct'].includes(operation) ? factValue.value : undefined,
    })).data
    message.value = '已更新记忆。'
  })
}

onUnmounted(() => {
  mounted = false
  clearTimeout(timer)
})
</script>

<template>
  <section class="border-b border-border px-4 py-2 text-chat-ui">
    <div class="chat-container space-y-2">
      <div class="flex gap-4">
        <button type="button" class="text-primary" :aria-expanded="panel === 'memory'" @click="toggle('memory')">会话记忆</button>
        <button type="button" class="text-primary" :aria-expanded="panel === 'support'" @click="toggle('support')">支持请求</button>
      </div>
      <div v-if="panel === 'memory'" class="space-y-2">
        <p>记忆版本 {{ memory.revision }}</p>
        <ul v-if="Object.keys(memory.facts).length" class="space-y-1">
          <li v-for="(value, key) in memory.facts" :key="key">{{ key }} · {{ value }}</li>
        </ul>
        <div class="flex flex-wrap gap-2">
          <input v-model="factKey" aria-label="事实名称或撤回短语" maxlength="120" placeholder="事实名称或撤回短语" class="rounded border border-border bg-background px-2 py-1">
          <input v-model="factValue" aria-label="事实值" maxlength="120" placeholder="事实值" class="rounded border border-border bg-background px-2 py-1">
        </div>
        <div class="flex flex-wrap gap-3">
          <button type="button" class="text-primary" :disabled="busy || !factKey.trim() || !factValue.trim()" @click="change('confirm')">确认</button>
          <button type="button" class="text-primary" :disabled="busy || !factKey.trim() || !factValue.trim()" @click="change('correct')">改写</button>
          <button type="button" class="text-primary" :disabled="busy || !factKey.trim()" @click="change('forget')">撤回</button>
          <button type="button" :disabled="busy" @click="change('clear')">清空记忆</button>
        </div>
      </div>
      <div v-if="panel === 'support'" class="space-y-2">
        <template v-if="preview">
          <p class="font-semibold">确认支持请求</p>
          <p class="break-words">{{ preview.summary }}</p>
          <div class="flex gap-3">
            <button type="button" class="text-primary" :disabled="busy" @click="confirm">确认加入本地队列</button>
            <button type="button" :disabled="busy" @click="preview = null">返回修改</button>
          </div>
        </template>
        <form v-else class="flex flex-wrap items-start gap-2" @submit.prevent="draft">
          <label class="sr-only" for="support-summary">支持请求说明</label>
          <textarea id="support-summary" v-model="summary" maxlength="600" rows="2" placeholder="简单说明遇到的问题" class="min-w-56 flex-1 rounded border border-border bg-background px-2 py-1" />
          <button type="submit" class="text-primary" :disabled="busy || summary.trim().length < 8">预览请求</button>
        </form>
        <ul v-if="tasks.length" class="max-h-36 space-y-1 overflow-y-auto">
          <li v-for="task in tasks" :key="task.task_id" class="flex flex-wrap items-center gap-2">
            <span>{{ labels[task.status] }}</span>
            <code v-if="task.receipt" class="break-all">{{ task.receipt }}</code>
            <button v-if="task.status === 'needs_review'" type="button" class="text-primary" :disabled="busy" @click="retry(task)">人工重试</button>
          </li>
        </ul>
      </div>
      <p v-if="message && panel" role="status">{{ message }}</p>
    </div>
  </section>
</template>
