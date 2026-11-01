import type { RunRequest } from './types'
import { capabilitiesView, requestBody, runView, snapshotView } from './v2'
import type { V2Capabilities, V2Run, V2Snapshot } from './v2'

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
const prefix = `${base}/api/competition/v2`

export class ApiError extends Error {
  constructor(message: string, readonly code = 'network_error') {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const timeout = AbortSignal.timeout(25_000)
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout
  let response: Response
  try {
    response = await fetch(`${prefix}${path}`, {
      ...options,
      signal,
      headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
      cache: 'no-store',
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError(timeout.aborted ? '服务响应超时。可以重新读取运行记录。' : '暂时无法连接服务。请检查服务连接后重试。')
  }
  let data: unknown
  try {
    data = await response.json()
  } catch {
    throw new ApiError('服务返回了无法读取的内容，请检查 API 连接。', 'invalid_response')
  }
  if (!response.ok) {
    const problem = data as { error?: { code?: string; message?: string } }
    throw new ApiError(problem.error?.message || `请求失败（HTTP ${response.status}）`, problem.error?.code)
  }
  return data as T
}

export const api = {
  async cases(signal: AbortSignal) {
    const data = await request<{ cases: V2Snapshot[] }>('/cases', { signal })
    if (!Array.isArray(data.cases)) throw new ApiError('病例列表格式不符合接口约定。', 'invalid_response')
    return data.cases.map((item, index) => snapshotView(item, index))
  },
  async snapshot(caseRef: string, signal: AbortSignal) {
    return snapshotView(await request<V2Snapshot>(`/cases/${encodeURIComponent(caseRef)}`, { signal }))
  },
  async capabilities(signal: AbortSignal) {
    return capabilitiesView(await request<V2Capabilities>('/capabilities', { signal }))
  },
  async start(body: RunRequest) {
    const data = await request<{ run_id: string }>('/runs', { method: 'POST', body: JSON.stringify(requestBody(body)) })
    if (!data.run_id || typeof data.run_id !== 'string') throw new ApiError('服务未返回运行编号，请核对服务记录。', 'invalid_response')
    return data.run_id
  },
  async run(runId: string, signal: AbortSignal) {
    const data = await request<V2Run>(`/runs/${encodeURIComponent(runId)}`, { signal })
    if (!data.run_id || !['queued', 'running', 'succeeded', 'partial', 'failed', 'blocked', 'needs_clarification'].includes(data.status) || !Array.isArray(data.events)) {
      throw new ApiError('运行记录格式不符合接口约定。', 'invalid_response')
    }
    return runView(data)
  },
}
