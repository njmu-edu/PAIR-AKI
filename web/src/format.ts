export function number(value: unknown, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: digits }) : '未提供'
}

export function percent(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${(value * 100).toFixed(1)}%` : '未提供'
}

export function date(value: string | number | null | undefined, short = false): string {
  if (value == null || value === '') return '未提供'
  const parsed = new Date(typeof value === 'number' ? value * 1000 : value)
  if (Number.isNaN(parsed.valueOf())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    ...(short ? {} : { year: 'numeric', month: '2-digit', day: '2-digit' }),
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(parsed)
}

export function age(days: number | null | undefined): string {
  if (days == null || !Number.isFinite(days)) return '年龄未提供'
  if (days < 30) return `${number(days, 0)} 天`
  if (days < 730) return `${number(days / 30.4375, 1)} 个月`
  return `${number(days / 365.25, 1)} 岁`
}

export const predictionMode = (mode: string) => ({
  synthetic: '合成预测演示', trained: '已训练模型 · 实际推理', live: '实际模型推理', recorded: '既有结果回放', unavailable: '预测暂不可用',
} as Record<string, string>)[mode] || `预测模式：${mode}`

export const plannerMode = (mode: string) => {
  if (mode === 'fixed') return '固定流程对照'
  if (['live', 'openai_compatible', 'llm', 'qwen'].includes(mode)) return '真实 LLM 模式'
  if (['synthetic', 'rule', 'rules', 'deterministic', 'rule_demo'].includes(mode)) return '规则流程演示'
  if (['unavailable', 'disabled'].includes(mode)) return 'LLM 暂不可用'
  return `规划模式：${mode}`
}

export const sourceLabel = (source: string) => source === 'synthetic' ? '合成病例' : source === 'approved_research' ? '获准研究病例' : source

export const taskLabel = (task: string) => ({ risk: '风险预测', similar: '相似病例', combined: '联合评估' } as Record<string, string>)[task] || task

export const statusLabel = (status: string) => ({
  queued: '等待执行', running: '正在评估', succeeded: '评估完成', partial: '部分完成', failed: '执行失败',
  verified: '核验通过', rejected: '动作未放行', passed: '校验通过', rule_demo: '规则流程演示',
  fixed: '固定流程', live: '真实 LLM', complete: '已完成', template: '固定表述', budget: '预算已到',
  no_new_evidence: '无新增证据',
  blocked: '资料受限', needs_clarification: '需要明确任务',
} as Record<string, string>)[status] || status

export const eventLabel = (kind: string) => ({
  runtime: '准备评估流程', runtime_verified: '结果核验完成', runtime_failure: '评估执行失败',
  queued: '任务已接收', started: '开始评估', plan: '制定下一步', planner: '规划动作',
  tool_call: '调用工具', tool_result: '取得工具结果', verify: '核验结果', verification: '结果核验',
  completed: '完成评估', failed: '执行失败', stopped: '结束执行', narrative: '组织结果说明',
  proposal: '提出下一动作', snapshot: '核对病例快照', tool_start: '开始执行工具',
  stop: '结束执行', narration: '组织有据说明', run_failure: '运行失败', planner_failure: '规划服务失败',
  coordinator_call: '协调器调用', medical_call: '专用模型调用', termination: '任务结束',
  goal_interpretation: '理解任务目标', plan_proposal: '提出执行计划',
} as Record<string, string>)[kind] || kind

export const toolLabel = (tool: string) => ({
  read_state: '读取病例状态', read_snapshot: '读取病例状态', get_state: '读取病例状态',
  fetch_evidence: '补取证据', retrieve_evidence: '补取证据', predict: '风险预测',
  predict_risk: '风险预测', retrieve_similar: '检索相似病例', search_similar: '检索相似病例',
  get_evidence: '补取病例证据', find_similar: '检索相似病例',
  read_case_state: '读取病例状态', predict_event_24h: '24小时事件预测', retrieve_comparable_cases: '检索可比病例',
} as Record<string, string>)[tool] || tool
