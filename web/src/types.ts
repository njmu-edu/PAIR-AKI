export type TaskType = 'risk' | 'similar' | 'combined'
export type ComparisonMode = 'domain_agent' | 'general_agent' | 'fixed'
export type SourceKind = 'synthetic' | 'approved_research'
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'blocked' | 'needs_clarification'

export interface Observation {
  ref: string
  value: number | null
  unit: string
  event_hours: number
  available_hours: number
  status: 'known' | 'conflict'
}

export interface Snapshot {
  case_ref: string
  snapshot_ref: string
  label: string
  decision_time: string
  age_days: number | null
  hours_since_admission: number | null
  source_kind: SourceKind
  gap_id: string | null
  features: Record<string, number | null>
  observations: Observation[]
  prediction_eligible?: boolean
  eligibility_reason: string | null
  evidence_complete?: boolean
  limitations: string[]
  endpoint: string
  version: string
}

export interface Capabilities {
  api_version: string
  prediction_mode: string
  llm_mode: string
  data_mode: string
  model_id: string | null
  research_evidence: Array<{ title: string; detail: string }>
}

export interface Comparison {
  key: string
  label: string
  query: number | null
  candidate: number | null
  status: string
  distance: number | null
}

export interface Match {
  case_ref: string
  snapshot_ref: string
  label: string
  decision_time: string
  source_kind: SourceKind
  score?: number
  coverage: number
  group_scores: Record<string, unknown>
  similarities: Comparison[]
  differences: Comparison[]
  missing: string[]
  observations: Observation[]
  evidence_refs: string[]
}

export interface Prediction {
  status: 'complete' | 'not_available'
  label: 0 | 1
  mode: 'trained' | 'synthetic'
  model_id?: string
  bundle_sha256?: string
  input_sha256: string
  reason?: string
}

export interface RunResult {
  prediction: Prediction | null
  similar_cases: {
    status: 'complete' | 'partial' | 'insufficient'
    matches: Match[]
    reason: string | null
    index_version: string
    index_sha256: string
    meaning: string
  } | null
  narrative: Array<{ id: string; text: string; evidence_refs: string[] }>
  evidence: Array<{ ref: string; source_kind: string; kind: string }>
  limitations: string[]
  final_snapshot: Snapshot
  versions: Record<string, unknown>
  metrics: { elapsed_seconds: number; tool_calls: number; llm_calls: number }
  planner_mode: string
  comparison_mode: string
  clarification?: string | null
}

export interface RunEvent {
  seq: number
  at: number
  kind: string
  tool?: string
  status?: string
  reason?: string
  details?: unknown
}

export interface RunRequest {
  case_ref: string
  snapshot_ref: string
  task: TaskType
  mode: ComparisonMode
  goal: string
}

export interface Run {
  run_id: string
  status: RunStatus
  request: RunRequest
  result: RunResult | null
  events: RunEvent[]
  created_at: number
  completed_at: number | null
}

export const isTerminal = (status: RunStatus) => ['succeeded', 'partial', 'failed', 'blocked', 'needs_clarification'].includes(status)

export type DrawerTab = 'summary' | 'trace' | 'sources' | 'observations' | 'match'
export interface DrawerView { tab: DrawerTab; match?: number }
