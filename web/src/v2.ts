import type { Capabilities, Match, Run, RunRequest, RunResult, Snapshot, TaskType } from './types'

export const taskGoals: Record<TaskType, string> = {
  risk: '请只预测这个病例未来24小时首次合格肌酐事件，输出0或1，不需要找相似病例。',
  similar: '请只找三名可比历史患者，解释相似与差异，不做事件预测。',
  combined: '请联合评估：预测未来24小时首次合格肌酐事件，并提供三名可比历史患者。',
}

export interface V2Capabilities {
  api_version: string
  coordinator: { mode: string; model_id: string }
  medical_models: Record<'M_P' | 'M_R', { mode: string; model_id: string }>
  source: { version: string; sha256: string }
}
export type V2Snapshot = Pick<Snapshot, 'case_ref' | 'snapshot_ref' | 'decision_time' | 'age_days' |
  'hours_since_admission' | 'source_kind' | 'features' | 'observations' | 'endpoint' | 'version'>
const caseLabels = new Map<string, string>()

export function snapshotView(raw: V2Snapshot, index?: number): Snapshot {
  if (index !== undefined) caseLabels.set(raw.case_ref, `${raw.source_kind === 'synthetic' ? '合成演示病例' : '研究病例'} ${String(index + 1).padStart(3, '0')}`)
  return { ...raw, label: caseLabels.get(raw.case_ref) ?? (raw.source_kind === 'synthetic' ? '合成演示病例' : '研究病例'), gap_id: null,
    eligibility_reason: null, limitations: [] }
}

export function capabilitiesView(raw: V2Capabilities): Capabilities {
  if (raw.api_version !== 'competition-v2') throw new Error('需要连接Agent API v2。')
  return { api_version: raw.api_version, prediction_mode: raw.medical_models.M_P.mode,
    llm_mode: raw.coordinator.mode, data_mode: raw.source.version === 'autonomous-fixtures-v1' ? 'synthetic' : raw.source.version === 'agent-registered-development-cases-v1' ? 'approved_research' : 'unknown',
    model_id: raw.medical_models.M_P.model_id, research_evidence: [] }
}

type V2Prediction = { label: 0 | 1; receipt: { mode: 'trained' | 'synthetic'; model_id: string;
  bundle_sha256: string; input_sha256: string } }
type V2Result = Omit<RunResult, 'prediction' | 'similar_cases' | 'final_snapshot' | 'metrics' | 'planner_mode'> & {
  prediction: V2Prediction | null
  comparables: (NonNullable<RunResult['similar_cases']> & { matches: Array<Match & { rank: number }> }) | null
  final_snapshot: V2Snapshot
  metrics: { elapsed_seconds: number; tool_calls: number; coordinator_calls: number }
  coordinator_mode: string
  goal_interpretation: { outcomes: string[] }
  termination: { clarification: string | null }
}
export type V2Run = Omit<Run, 'result' | 'request'> & {
  request: { goal: string; case_ref: string; snapshot_ref: string; mode: 'autonomous' | 'general' | 'fixed' }
  result: V2Result | null
}

export function runView(raw: V2Run): Run {
  const source = raw.result
  let task = (Object.keys(taskGoals) as TaskType[]).find(k => taskGoals[k] === raw.request.goal) ?? 'combined'
  const outcomes = source?.goal_interpretation?.outcomes
  if (outcomes?.length === 1) task = outcomes[0] === 'event_prediction' ? 'risk' : 'similar'
  const prediction = source?.prediction
  if (prediction && prediction.label !== 0 && prediction.label !== 1) throw new Error('预测器未返回合法的0/1结果。')
  return { ...raw, request: { ...raw.request, task,
    mode: raw.request.mode === 'autonomous' ? 'domain_agent' : raw.request.mode === 'general' ? 'general_agent' : 'fixed' },
    result: source ? { ...source, prediction: prediction ? { status: 'complete', label: prediction.label,
      ...prediction.receipt } : null,
      similar_cases: source.comparables ? { ...source.comparables,
        matches: source.comparables.matches.map((m, i) => ({ ...m, label: `参考病例 ${i + 1}` })),
        meaning: '专用重排模型选择的可比病例；相似不代表诊断或治疗结果相同。' } : null,
      final_snapshot: snapshotView(source.final_snapshot), planner_mode: source.coordinator_mode,
      clarification: source.termination?.clarification,
      metrics: { ...source.metrics, llm_calls: source.metrics.coordinator_calls } } : null }
}

export function requestBody(request: RunRequest) {
  return { case_ref: request.case_ref, snapshot_ref: request.snapshot_ref, goal: request.goal,
    mode: request.mode === 'domain_agent' ? 'autonomous' : request.mode === 'general_agent' ? 'general' : 'fixed' }
}
