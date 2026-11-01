import { useEffect, useRef } from 'react'
import type { Capabilities, DrawerTab, DrawerView, Match, Run, Snapshot } from '../types'
import { cx } from '../cx'
import { comparisonLabel } from '../comparison'
import { date, eventLabel, number, percent, plannerMode, predictionMode, sourceLabel, statusLabel, taskLabel, toolLabel } from '../format'
import { Icon } from './Icon'
import { ObservationTable, TrendChart } from './TrendChart'

const tabs: Array<{ id: Exclude<DrawerTab, 'match'>; label: string }> = [
  { id: 'summary', label: '评估说明' },
  { id: 'trace', label: '执行过程' },
  { id: 'sources', label: '来源与版本' },
  { id: 'observations', label: '病例观测' },
]

function DetailValue({ value }: { value: unknown }) {
  if (value == null) return <>未提供</>
  if (typeof value === 'string' || typeof value === 'number') return <>{String(value)}</>
  return <pre>{JSON.stringify(value, null, 2)}</pre>
}

function SummaryTab({ run, onView }: { run: Run | null; onView: (view: DrawerView) => void }) {
  const result = run?.result
  if (!result) return <p className="muted">运行结束后展示评估说明与仍需保留的限制。</p>
  return <>
    {result.clarification && <div className="notice" role="status"><p>{result.clarification} 请修改任务描述后重新发起。</p></div>}
    {result.narrative.length ? <div className="narrative-items">{result.narrative.map((item) => <div key={item.id}><p>{item.text}</p>{item.evidence_refs.length > 0 && <button onClick={() => onView({ tab: 'sources' })} className="text-button small"><Icon name="link" size={13} />{item.evidence_refs.length} 条来源依据</button>}</div>)}</div> : <p className="muted">本次运行没有生成说明，请查看工具结果与限制。</p>}
    {result.limitations.length > 0 && <div className="limitations"><h3><Icon name="alert" size={16} />仍需保留的限制</h3><ul>{result.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
  </>
}

function TraceTab({ run }: { run: Run | null }) {
  if (!run) return <p className="muted">开始评估后，这里记录真实的工具反馈与执行事件。</p>
  const result = run.result
  return <>
    <dl className="overview-list">
      <div><dt>运行编号</dt><dd className="mono">{run.run_id}</dd></div>
      <div><dt>任务</dt><dd>{taskLabel(run.request.task)} · {statusLabel(run.status)}</dd></div>
      <div><dt>规划方式</dt><dd>{result ? plannerMode(result.planner_mode) : '以执行事件为准'}</dd></div>
      <div><dt>开始时间</dt><dd>{date(run.created_at)}（北京时间）</dd></div>
    </dl>
    {result && <div className="run-metrics"><div><strong>{number(result.metrics.elapsed_seconds, 2)}<small>s</small></strong><span>执行耗时</span></div><div><strong>{number(result.metrics.tool_calls, 0)}</strong><span>工具调用</span></div><div><strong>{number(result.metrics.llm_calls, 0)}</strong><span>LLM 调用</span></div></div>}
    <h3 className="drawer-subtitle">执行记录 · {run.events.length} 个事件</h3>
    {run.events.length ? <ol className="event-list">{run.events.map((event) => <li key={event.seq}><span className={cx('event-marker', (event.status === 'failed' || event.kind === 'failed') && 'failed')}>{event.seq}</span><div><div className="event-title"><strong>{eventLabel(event.kind)}{event.tool && <span> · {toolLabel(event.tool)}</span>}</strong><time>{date(event.at, true)}</time></div>{event.status && <span className="event-status">{statusLabel(event.status)}</span>}{event.reason && <p>{event.reason}</p>}{event.details != null && <details className="raw-details"><summary>查看工具回执</summary><pre>{JSON.stringify(event.details, null, 2)}</pre></details>}</div></li>)}</ol> : <p className="muted">任务已受理，等待首个执行事件。</p>}
  </>
}

function SourcesTab({ run, capabilities }: { run: Run | null; capabilities: Capabilities | null }) {
  const result = run?.result
  return <>
    {result ? <>
      <h3 className="drawer-subtitle">来源证据</h3>
      <div className="evidence-list">{result.evidence.length ? result.evidence.map((item, index) => <div className="evidence-item" key={item.ref + '-' + index}><Icon name="file" size={16} /><div><code>{item.ref}</code><span>{sourceLabel(item.source_kind)} · {item.kind}</span></div></div>) : <p className="muted">本次运行未返回来源证据。</p>}</div>
      <h3 className="drawer-subtitle">模型、输入与检索身份</h3>
      <dl className="version-list">
        {result.prediction && <><div><dt>预测模式</dt><dd>{predictionMode(result.prediction.mode)}</dd></div><div><dt>模型</dt><dd>{result.prediction.model_id || '未提供'}</dd></div><div><dt>模型包 SHA-256</dt><dd>{result.prediction.bundle_sha256 || '未提供'}</dd></div><div><dt>输入 SHA-256</dt><dd>{result.prediction.input_sha256 || '未提供'}</dd></div></>}
        {result.similar_cases && <><div><dt>检索索引版本</dt><dd>{result.similar_cases.index_version}</dd></div><div><dt>索引 SHA-256</dt><dd>{result.similar_cases.index_sha256}</dd></div></>}
        <div><dt>快照版本</dt><dd>{result.final_snapshot.version}</dd></div>
        <div><dt>快照引用</dt><dd>{result.final_snapshot.snapshot_ref}</dd></div>
        <div><dt>研究端点</dt><dd>{result.final_snapshot.endpoint}</dd></div>
        {Object.entries(result.versions).map(([key, value]) => <div key={key}><dt>{key}</dt><dd><DetailValue value={value} /></dd></div>)}
      </dl>
    </> : <p className="muted">运行结束后可读取结果所绑定的来源与版本。当前进展见“执行过程”。</p>}
    {capabilities?.research_evidence?.length ? <><h3 className="drawer-subtitle">已有研究基础</h3><div className="foundation-list">{capabilities.research_evidence.map((item, index) => <article key={index}><h4>{item.title}</h4><p>{item.detail}</p></article>)}</div></> : null}
  </>
}

function MatchTab({ match, rank, queryObservations, onView }: { match: Match | undefined; rank: number; queryObservations: Snapshot['observations']; onView: (view: DrawerView) => void }) {
  if (!match) return <p className="muted">未找到该参考病例。</p>
  const items = [...new Map([...match.similarities, ...match.differences].map((item) => [item.key, item])).values()]
  const rows = (list: Match['similarities'], empty: string) => list.length ? <ul className="comparison-list">{list.map((item) => <li key={item.key}><span>{comparisonLabel(item)}</span><span>{number(item.query, 2)} <i>→</i> {number(item.candidate, 2)}</span></li>)}</ul> : <p className="muted">{empty}</p>
  return <>
    <div className="match-detail-head"><span className="match-rank">{rank}</span><div><strong>{match.label}</strong><span>{sourceLabel(match.source_kind)} · 评估时点 {date(match.decision_time)}</span></div><div className="match-coverage"><strong>{percent(match.coverage)}</strong><span>共同信息覆盖</span></div></div>
    <div className="drawer-chart"><TrendChart observations={match.observations} comparison={queryObservations} label={match.label + ' 与当前病例的肌酐变化对照'} /></div>
    <div className="comparison-block"><h3><i className="legend-dot" />主要相似处</h3>{rows(match.similarities, '服务未提供共同相似项')}</div>
    <div className="comparison-block difference-block"><h3><i className="legend-dot" />需要留意的差异</h3>{rows(match.differences, '服务未列出明显差异；不代表病例等同。')}</div>
    {match.missing.length > 0 && <p className="match-missing"><Icon name="alert" size={14} /><span>比较缺口：{match.missing.join('、')}</span></p>}
    <h3 className="drawer-subtitle">全部比较项（当前 → 参考）</h3>
    <div className="table-scroll"><table><thead><tr><th>比较项</th><th>当前</th><th>参考</th></tr></thead><tbody>{items.map((item) => <tr key={item.key}><td>{comparisonLabel(item)}</td><td>{number(item.query, 3)}</td><td>{number(item.candidate, 3)}</td></tr>)}</tbody></table></div>
    <dl className="overview-list"><div><dt>病例引用</dt><dd className="mono">{match.case_ref}</dd></div><div><dt>快照引用</dt><dd className="mono">{match.snapshot_ref}</dd></div></dl>
    {match.evidence_refs.length > 0 && <div className="reference-list">{match.evidence_refs.map((ref) => <button className="reference" key={ref} onClick={() => onView({ tab: 'sources' })}><Icon name="link" size={12} />{ref}</button>)}</div>}
  </>
}

export function EvidenceDrawer({ run, snapshot, capabilities, open, view, onView, onClose }: {
  run: Run | null; snapshot: Snapshot | null; capabilities: Capabilities | null
  open: boolean; view: DrawerView; onView: (view: DrawerView) => void; onClose: () => void
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose })
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') closeRef.current() }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); previous?.focus?.() }
  }, [open])
  if (!open) return null

  const matches = run?.result?.similar_cases?.matches || []
  const matchIndex = view.match ?? 0
  const queryObservations = run?.result?.final_snapshot.observations || snapshot?.observations || []
  const title = view.tab === 'match' ? (matches[matchIndex]?.label || '参考病例') + ' · 对照' : '过程与证据'
  return <div className="drawer-root">
    <div className="drawer-backdrop" onClick={onClose} />
    <aside className="drawer" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panelRef}>
      <header className="drawer-head"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭"><Icon name="close" size={18} /></button></header>
      <nav className="drawer-tabs" role="tablist" aria-label="过程与证据">
        {tabs.map((tab) => <button key={tab.id} role="tab" aria-selected={view.tab === tab.id} className={cx('drawer-tab', view.tab === tab.id && 'active')} onClick={() => onView({ tab: tab.id })}>{tab.label}</button>)}
      </nav>
      <div className="drawer-body">
        {view.tab === 'summary' && <SummaryTab run={run} onView={onView} />}
        {view.tab === 'trace' && <TraceTab run={run} />}
        {view.tab === 'sources' && <SourcesTab run={run} capabilities={capabilities} />}
        {view.tab === 'observations' && <ObservationTable observations={snapshot?.observations || []} />}
        {view.tab === 'match' && <MatchTab match={matches[matchIndex]} rank={matchIndex + 1} queryObservations={queryObservations} onView={onView} />}
      </div>
    </aside>
  </div>
}
