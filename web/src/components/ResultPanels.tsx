import type { DrawerView, Match, Observation, Run, Snapshot, TaskType } from '../types'
import { isTerminal } from '../types'
import { cx } from '../cx'
import { comparisonLabel } from '../comparison'
import { age, number, percent, predictionMode, sourceLabel } from '../format'
import { Icon, Spinner } from './Icon'
import { TrendChart } from './TrendChart'

type OpenDrawer = (view: DrawerView) => void

export function SnapshotCard({ snapshot, loading, onOpen }: { snapshot: Snapshot | null; loading: boolean; onOpen: OpenDrawer }) {
  return <section className="card snapshot-card" aria-labelledby="snapshot-heading">
    <header className="card-head">
      <div><h2 id="snapshot-heading">当前病例状态</h2>{snapshot && <p>{snapshot.label} · {age(snapshot.age_days)} · 入院后 {number(snapshot.hours_since_admission)} h</p>}</div>
      {snapshot && <span className={cx('badge', snapshot.source_kind === 'synthetic' ? 'badge-amber' : 'badge-muted')}>{sourceLabel(snapshot.source_kind)}</span>}
    </header>
    {loading ? <div className="card-placeholder" role="status"><Spinner />读取指定时点的病例状态</div> : snapshot ? <>
      <div className="fact-grid">
        <div><span>当前肌酐</span><strong>{number(snapshot.features.latest_umol_l)}<small>µmol/L</small></strong></div>
        <div><span>168 h 参考值</span><strong>{number(snapshot.features.reference168_umol_l)}<small>µmol/L</small></strong></div>
        <div><span>相对参考值</span><strong>{number(snapshot.features.ratio168, 2)}<small>倍</small></strong></div>
      </div>
      <TrendChart observations={snapshot.observations} />
      <button className="text-button card-link" onClick={() => onOpen({ tab: 'observations' })}>查看 {snapshot.observations.length} 条原始观测 <Icon name="arrow" size={14} /></button>
    </> : <div className="card-placeholder"><Icon name="file" size={26} /><p>选择一个病例，查看指定时点的状态与病程。</p></div>}
  </section>
}

export function PredictionCard({ run, busy, task, onOpen }: { run: Run | null; busy: boolean; task: TaskType; onOpen: OpenDrawer }) {
  const prediction = run?.result?.prediction
  const valid = prediction?.status === 'complete' && (prediction.label === 0 || prediction.label === 1)
  const selected = task !== 'similar'
  const ended = Boolean(run && isTerminal(run.status))
  const verdict = busy && selected ? '正在评估' : valid ? (prediction.label === 1 ? '模型预测发生' : '模型预测不发生') : !selected ? '本任务无需预测' : ended ? '未产生有效预测' : '等待评估'
  return <section className="card prediction-card" aria-labelledby="prediction-heading">
    <header className="card-head"><div><h2 id="prediction-heading">未来 24 小时</h2><p>首次合格肌酐事件</p></div></header>
    <div className={cx('prediction-result', valid && (prediction.label === 1 ? 'is-positive' : 'is-negative'))}>
      <strong className="prediction-value">{busy && selected ? <Spinner /> : valid ? prediction.label : '—'}</strong>
      <div><p className="verdict">{verdict}</p><span className="prediction-scale">二值事件预测 · 0 / 1</span></div>
    </div>
    {prediction ? <>
      <span className={cx('badge', prediction.mode === 'synthetic' ? 'badge-amber' : 'badge-teal')}>{predictionMode(prediction.mode)}</span>
      <p className="prediction-reason">{prediction.reason || (prediction.mode === 'synthetic' ? '合成演示值，仅用于验证界面与执行流程。' : '数值直接引用预测工具，解释过程不改写预测值。')}</p>
      <button className="text-button" onClick={() => onOpen({ tab: 'sources' })}>模型与输入依据 <Icon name="arrow" size={14} /></button>
    </> : <p className="prediction-reason">{!selected ? '当前仅检索可比病例，不会额外调用预测工具。' : ended ? '本次运行未返回可用预测，请查看执行记录。' : '开始评估后展示预测值、模式与适用限制。'}</p>}
  </section>
}

export function SummaryCard({ run, onOpen }: { run: Run | null; onOpen: OpenDrawer }) {
  const result = run?.result
  const first = result?.narrative[0]
  return <section className="card summary-card" aria-labelledby="summary-heading">
    <header className="card-head"><div><h2 id="summary-heading">评估说明</h2><p>只陈述有来源的内容</p></div></header>
    {result ? <>
      <div className="summary-body">
        {result.clarification && <p className="summary-clarify" role="status">{result.clarification} 请修改任务描述后重新发起。</p>}
        {first ? <p className="summary-text">{first.text}</p> : !result.clarification && <p className="muted">本次运行没有生成说明，请查看工具结果与限制。</p>}
      </div>
      <div className="summary-foot">
        <button className="text-button" onClick={() => onOpen({ tab: 'summary' })}>完整说明{result.narrative.length > 1 ? '（' + result.narrative.length + ' 段）' : ''} <Icon name="arrow" size={14} /></button>
        {result.limitations.length > 0 && <button className="chip-button" onClick={() => onOpen({ tab: 'summary' })}><Icon name="alert" size={13} />{result.limitations.length} 条限制</button>}
      </div>
    </> : <div className="card-placeholder"><Icon name="file" size={26} /><p>运行结束后，这里给出带来源依据的评估说明与限制。</p></div>}
  </section>
}

const firstComparison = (items: Match['similarities'], empty: string) => {
  const item = items[0]
  return item ? comparisonLabel(item) + ' ' + number(item.query, 2) + ' → ' + number(item.candidate, 2) : empty
}

function MatchCard({ match, rank, queryObservations, onOpen }: { match: Match; rank: number; queryObservations: Observation[]; onOpen: OpenDrawer }) {
  const coverage = typeof match.coverage === 'number' ? Math.max(0, Math.min(1, match.coverage)) : 0
  return <article className="card match-card">
    <header className="match-head">
      <span className="match-rank">{rank}</span>
      <div><h3>{match.label}</h3><p>{sourceLabel(match.source_kind)} · 专用模型重排</p></div>
      <div className="match-coverage"><strong>{percent(match.coverage)}</strong><span>信息覆盖</span></div>
    </header>
    <TrendChart observations={match.observations} comparison={queryObservations} compact label={match.label + ' 与当前病例的肌酐变化对照'} />
    <ul className="match-notes">
      <li className="note-similar"><i />{firstComparison(match.similarities, '服务未提供共同相似项')}</li>
      <li className="note-diff"><i />{firstComparison(match.differences, '服务未列出明显差异，不代表病例等同')}</li>
    </ul>
    <footer className="match-foot">
      <span className="coverage-track" aria-hidden="true"><span style={{ width: coverage * 100 + '%' }} /></span>
      <button className="text-button" onClick={() => onOpen({ tab: 'match', match: rank - 1 })}>比较明细 <Icon name="arrow" size={14} /></button>
    </footer>
  </article>
}

export function SimilarStrip({ run, busy, task, onOpen }: { run: Run | null; busy: boolean; task: TaskType; onOpen: OpenDrawer }) {
  const similar = run?.result?.similar_cases
  const matches = similar?.matches.slice(0, 3) || []
  const queryObservations = run?.result?.final_snapshot.observations || []
  const note = similar?.meaning || '工程相似度用于排列可比病例，不是风险、诊断或疗效概率。'
  return <section className="similar-strip" aria-labelledby="similar-heading">
    <header className="strip-head">
      <h2 id="similar-heading">相似病例参考<span className="count-badge">{matches.length}</span></h2>
      <p title={note}>{matches.length > 0 ? note + (similar?.reason ? ' ' + similar.reason : '') : '最多 3 名不同患者，同一时间坐标下对照'}</p>
    </header>
    {matches.length > 0
      ? <div className="match-grid">{matches.map((match, index) => <MatchCard key={match.case_ref + '-' + match.snapshot_ref} match={match} rank={index + 1} queryObservations={queryObservations} onOpen={onOpen} />)}</div>
      : <div className="card strip-empty">
        <span className="empty-icon"><Icon name="search" size={22} /></span>
        <div>
          <h3>{busy && task !== 'risk' ? '正在寻找可比病例' : similar ? '暂无满足条件的可比病例' : task === 'risk' ? '本次任务只进行风险预测' : '把相似病例放在同一时间坐标下'}</h3>
          <p>{similar?.reason || (task === 'risk' ? '如需病例对照，请选择“相似病例”或“联合评估”。' : '评估后展示每名病例的相似项、差异与共同信息覆盖。')}</p>
        </div>
        {busy && task !== 'risk' && <Spinner />}
      </div>}
  </section>
}
