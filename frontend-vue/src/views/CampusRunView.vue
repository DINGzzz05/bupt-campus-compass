<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Code2, RefreshCw } from 'lucide-vue-next'
import { campusTraceUrl, fetchCampusTrace, type CampusRunTrace, type TraceStep } from '@/api/campusTrace'
import { useChatStore } from '@/stores/chat'

const route = useRoute()
const sessionId = computed(() => String(route.params.sessionId))
const apiUrl = computed(() => campusTraceUrl(sessionId.value, String(route.params.runId)))
const trace = ref<CampusRunTrace | null>(null)
const loading = ref(true)
const error = ref('')
const refresh = ref(0)
const chatStore = useChatStore()

onMounted(() => {
  if (!chatStore.sessions.length && !chatStore.sessionsLoading) {
    void chatStore.fetchSessions().catch(() => undefined)
  }
})

watch(
  [apiUrl, refresh],
  async ([url], _previous, onCleanup) => {
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    trace.value = null
    loading.value = true
    error.value = ''
    try {
      const result = await fetchCampusTrace(url, controller.signal)
      if (!controller.signal.aborted) trace.value = result
    } catch (cause) {
      if (!controller.signal.aborted) {
        error.value = cause instanceof Error && /[\u3400-\u9fff]/.test(cause.message)
          ? cause.message
          : '暂时无法加载追踪记录，请重试。'
      }
    } finally {
      if (!controller.signal.aborted) loading.value = false
    }
  },
  { immediate: true },
)

const stages: Record<string, string> = {
  domain: '领域路由', risk: '风险判断', memory: '会话记忆', retrieval: '资料检索', review: '来源审查',
}
const purposes: Record<string, string> = {
  route: '领域路由', risk: '风险判断', summary: '记忆摘要', answer: '回答生成',
}
const domains: Record<string, string> = {
  academic: '教务', research: '科研资源', campus: '校园生活', development: '学生发展', general: '通用咨询',
}
const risks: Record<string, string> = {
  allowed: '允许', blocked: '已拦截', support_confirmation: '需确认支持请求',
}
const statuses: Record<string, string> = {
  completed: '已完成', running: '运行中', interrupted: '已中断', cancelled: '已取消', failed: '失败',
  queued: '待处理', needs_review: '待人工处理',
}
const outcomes: Record<string, string> = { ok: '成功', failed: '失败', circuit_open: '已熔断', cancelled: '已取消' }
const retrievalModes: Record<string, string> = { bm25_chroma: 'BM25 + Chroma', bm25: 'BM25', bm25_fallback: 'BM25（回退）' }
const memoryModes: Record<string, string> = {
  redis_hit: 'Redis 命中', redis_refresh: 'Redis 已刷新', sql_fallback: 'SQL 回退', sql: 'SQL', skipped: '已跳过',
}
const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'medium' })

function label(values: Record<string, string>, value?: string | null): string {
  return value ? (values[value] ?? value) : '—'
}

function duration(value: number): string {
  return `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ms`
}

function timestamp(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date)
}

function stepDetail(step: TraceStep): string {
  if (step.agent === 'domain') return label(domains, step.decision)
  if (step.agent === 'risk') return label(risks, step.decision)
  if (step.agent === 'memory') {
    return [
      label(memoryModes, step.window),
      step.revision != null ? `版本 ${step.revision}` : '',
      step.snapshot_id != null ? `快照 #${step.snapshot_id}` : '',
    ].filter(Boolean).join(' · ')
  }
  if (step.agent === 'retrieval') return `选中 ${step.sources?.length ?? 0} 份资料`
  if (step.agent === 'review') return `通过 ${step.accepted ?? 0} 份 · 拒绝 ${step.rejected ?? 0} 份`
  return step.decision ?? '—'
}

const candidateGroups = computed(() => {
  const retrieval = trace.value?.retrieval
  return retrieval
    ? [
        { name: '排序结果', ids: retrieval.ranked_candidate_ids },
        { name: 'BM25 候选', ids: retrieval.lexical_candidate_ids },
        { name: '向量候选', ids: retrieval.vector_candidate_ids },
      ]
    : []
})
</script>

<template>
  <main id="main-content" class="flex-1 min-h-0 overflow-y-auto" :aria-busy="loading">
    <div class="mx-auto w-full max-w-6xl space-y-5 px-4 py-6 sm:px-7 sm:py-8">
      <header>
        <RouterLink :to="`/chat/${sessionId}`" class="inline-flex items-center gap-2 text-sm text-primary hover:underline">
          <ArrowLeft class="size-4" aria-hidden="true" /> 返回会话
        </RouterLink>
        <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
          <h1 class="flex flex-wrap items-center gap-3 text-2xl font-semibold">
            请求追踪
            <span
              v-if="trace"
              class="rounded-full px-2.5 py-1 text-xs font-medium"
              :class="trace.status === 'completed'
                ? 'bg-success-subtle text-success-subtle-foreground'
                : 'bg-muted text-muted-foreground'"
            >{{ label(statuses, trace.status) }}</span>
          </h1>
          <a
            v-if="trace"
            :href="apiUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm hover:bg-muted"
          ><Code2 class="size-4" aria-hidden="true" /> 原始 JSON</a>
        </div>
      </header>

      <p v-if="loading" role="status" class="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        正在加载追踪记录…
      </p>
      <div v-else-if="error" class="rounded-xl border border-border bg-card p-5">
        <p role="alert" class="text-sm">{{ error }}</p>
        <button type="button" class="mt-3 inline-flex items-center gap-2 text-sm text-primary hover:underline" @click="refresh++">
          <RefreshCw class="size-4" aria-hidden="true" /> 重新加载
        </button>
      </div>

      <template v-else-if="trace">
        <section aria-label="运行概况" class="rounded-xl border border-border bg-card p-5">
          <dl class="grid grid-cols-2 gap-x-5 gap-y-4 text-sm lg:grid-cols-4">
            <div><dt class="text-muted-foreground">业务领域</dt><dd class="mt-1 font-medium">{{ label(domains, trace.domain) }}</dd></div>
            <div><dt class="text-muted-foreground">风险判断</dt><dd class="mt-1 font-medium">{{ label(risks, trace.risk) }}</dd></div>
            <div><dt class="text-muted-foreground">开始时间</dt><dd class="mt-1 font-medium">{{ timestamp(trace.started_at) }}</dd></div>
            <div><dt class="text-muted-foreground">结束时间</dt><dd class="mt-1 font-medium">{{ timestamp(trace.finished_at) }}</dd></div>
          </dl>
          <details class="mt-4 border-t border-border pt-3 text-sm">
            <summary class="cursor-pointer text-muted-foreground">请求标识</summary>
            <dl class="mt-3 space-y-2">
              <div><dt class="inline text-muted-foreground">Run ID</dt> <dd class="inline break-all font-mono text-xs">{{ trace.run_id }}</dd></div>
              <div><dt class="inline text-muted-foreground">Request ID</dt> <dd class="inline break-all font-mono text-xs">{{ trace.request_id }}</dd></div>
            </dl>
          </details>
        </section>

        <div class="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <section class="min-w-0 rounded-xl border border-border bg-card p-5">
            <h2 class="text-base font-semibold">执行步骤</h2>
            <ol v-if="trace.artifacts.length" class="mt-4 space-y-4 border-l border-border pl-4 text-sm">
              <li v-for="step in trace.artifacts" :key="step.agent" class="relative">
                <span aria-hidden="true" class="absolute -left-[21px] top-1.5 size-2 rounded-full bg-primary ring-2 ring-card" />
                <p class="font-medium">{{ label(stages, step.agent) }}</p>
                <p class="mt-1 text-muted-foreground">{{ stepDetail(step) }}</p>
              </li>
            </ol>
            <p v-else class="mt-3 text-sm text-muted-foreground">暂无执行步骤。</p>
          </section>

          <section class="min-w-0 rounded-xl border border-border bg-card p-5">
            <h2 class="text-base font-semibold">检索结果</h2>
            <template v-if="trace.retrieval">
              <dl class="mt-4 flex flex-wrap gap-x-5 gap-y-3 text-sm">
                <div><dt class="text-muted-foreground">检索方式</dt><dd class="mt-1 font-medium">{{ label(retrievalModes, trace.retrieval.retrieval) }}</dd></div>
                <div><dt class="text-muted-foreground">检索耗时</dt><dd class="mt-1 font-medium tabular-nums">{{ duration(trace.retrieval.retrieval_ms) }}</dd></div>
                <div><dt class="text-muted-foreground">语料版本</dt><dd class="mt-1 break-all font-mono text-xs">{{ trace.retrieval.corpus_version }}</dd></div>
              </dl>
              <div class="mt-4 space-y-3">
                <details v-for="(group, index) in candidateGroups" :key="group.name" class="rounded-md border border-border px-3 py-2 text-sm" :open="index === 0">
                  <summary class="cursor-pointer font-medium">{{ group.name }}（{{ group.ids.length }}）</summary>
                  <ol v-if="group.ids.length" class="mt-2 list-decimal space-y-1 pl-5">
                    <li v-for="id in group.ids" :key="id" class="break-all py-0.5 font-mono text-xs text-muted-foreground">{{ id }}</li>
                  </ol>
                  <p v-else class="mt-2 text-muted-foreground">无匹配资料。</p>
                </details>
              </div>
            </template>
            <p v-else class="mt-3 text-sm text-muted-foreground">本轮没有检索记录。</p>
          </section>
        </div>

        <section class="rounded-xl border border-border bg-card p-5">
          <h2 class="text-base font-semibold">模型调用</h2>
          <div v-if="trace.model_attempts.length" class="mt-3 overflow-x-auto">
            <table class="w-full min-w-[32rem] text-left text-sm">
              <thead class="border-b border-border text-muted-foreground">
                <tr>
                  <th scope="col" class="py-2 pr-4 font-medium">用途</th>
                  <th scope="col" class="py-2 pr-4 font-medium">模型</th>
                  <th scope="col" class="py-2 pr-4 font-medium">结果</th>
                  <th scope="col" class="py-2 pr-4 font-medium">耗时</th>
                  <th scope="col" class="py-2 font-medium">输入 Token</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-border">
                <tr v-for="(attempt, index) in trace.model_attempts" :key="index">
                  <td class="py-2.5 pr-4 font-medium">{{ label(purposes, attempt.purpose) }}</td>
                  <td class="py-2.5 pr-4 font-mono text-xs">{{ attempt.model }}</td>
                  <td class="py-2.5 pr-4">
                    {{ label(outcomes, attempt.outcome) }}
                    <span v-if="attempt.failure" class="block break-all font-mono text-xs text-muted-foreground">{{ attempt.failure }}</span>
                  </td>
                  <td class="whitespace-nowrap py-2.5 pr-4 tabular-nums">{{ duration(attempt.elapsed_ms) }}</td>
                  <td class="py-2.5 tabular-nums">{{ attempt.input_tokens ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="mt-3 text-sm text-muted-foreground">本轮没有模型调用。</p>
        </section>

        <section v-if="trace.memory_snapshot_ids.length || trace.actions.length" class="rounded-xl border border-border bg-card p-5">
          <h2 class="text-base font-semibold">关联记录</h2>
          <p v-if="trace.memory_snapshot_ids.length" class="mt-3 text-sm">
            会话快照 {{ trace.memory_snapshot_ids.map((id) => `#${id}`).join('、') }}
          </p>
          <ul v-if="trace.actions.length" class="mt-3 space-y-2 text-sm">
            <li v-for="action in trace.actions" :key="action.task_id">
              支持任务 <code class="break-all text-xs">{{ action.task_id }}</code>
              · {{ label(statuses, action.status) }} · 已尝试 {{ action.attempts }} 次
              <span v-if="action.receipt" class="block break-all text-muted-foreground">回执 {{ action.receipt }}</span>
              <span v-if="action.failure" class="block break-all text-muted-foreground">{{ action.failure }}</span>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </main>
</template>
