import client from './client'

export interface CampusRunTrace {
  run_id: string
  request_id: string
  session_id: number
  status: string
  domain: string | null
  risk: string | null
  started_at: string
  finished_at: string | null
  artifacts: TraceStep[]
  retrieval: {
    retrieval: string
    retrieval_ms: number
    corpus_version: string
    lexical_candidate_ids: string[]
    vector_candidate_ids: string[]
    ranked_candidate_ids: string[]
  } | null
  memory_snapshot_ids: number[]
  model_attempts: {
    purpose: string
    model: string
    outcome: string
    elapsed_ms: number
    input_tokens: number | null
    failure: string | null
  }[]
  actions: {
    task_id: string
    status: string
    attempts: number
    receipt: string | null
    failure: string | null
  }[]
}

export interface TraceStep {
  agent: string
  decision?: string
  window?: string
  revision?: number | null
  snapshot_id?: number | null
  sources?: string[]
  accepted?: number
  rejected?: number
}

export function campusTraceUrl(sessionId: string, runId: string): string {
  return `/api/bupt/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}`
}

export async function fetchCampusTrace(url: string, signal: AbortSignal): Promise<CampusRunTrace> {
  const { data, status } = await client.get<CampusRunTrace>(url, {
    signal,
    validateStatus: (code) => code === 200 || code === 403 || code === 404,
  })
  if (status !== 200) throw new Error('找不到这条追踪记录，或当前账号无法访问。')
  if (!data?.run_id) throw new Error('没有收到有效的追踪记录。')
  return data
}
