import { useCallback, useState } from 'react'
import type { DrawerView } from './types'
import { cx } from './cx'
import { plannerMode, predictionMode } from './format'
import { CommandPanel } from './components/CommandPanel'
import { EvidenceDrawer } from './components/EvidenceDrawer'
import { HistoryMenu } from './components/HistoryMenu'
import { Icon } from './components/Icon'
import { PredictionCard, SimilarStrip, SnapshotCard, SummaryCard } from './components/ResultPanels'
import { RunBar } from './components/RunBar'
import { useWorkspace } from './useWorkspace'

const dataModeText = (mode: string) => mode === 'synthetic' ? '合成病例演示 · 不含真实患者资料'
  : mode === 'approved_research' ? '已获准研究数据 · 仅限授权用途' : '数据模式：' + mode

export default function App() {
  const workspace = useWorkspace()
  const [view, setView] = useState<DrawerView>({ tab: 'summary' })
  const { capabilities, run, busy, bootLoading, snapshotLoading, task, setTraceOpen } = workspace
  const snapshot = run?.result?.final_snapshot || workspace.snapshot
  const connected = Boolean(capabilities && !workspace.bootError)

  const openDrawer = useCallback((next: DrawerView) => { setView(next); setTraceOpen(true) }, [setTraceOpen])
  const closeDrawer = useCallback(() => setTraceOpen(false), [setTraceOpen])
  const loadRun = (id: string) => { setView({ tab: 'trace' }); workspace.loadRun(id) }

  return <div className="app-shell">
    <a className="skip-link" href="#workspace-main">跳到评估工作区</a>
    <header className="topbar">
      <a className="brand" href="./" aria-label="PAIR-AKI｜肾见 首页">
        <span className="brand-symbol"><Icon name="pulse" size={21} /></span>
        <span className="brand-name">PAIR-AKI<span>｜</span>肾见</span>
      </a>
      <div className="topbar-right">
        <div className="status-cluster" aria-label="运行环境状态">
          <span className={cx('status-pill', connected && 'is-connected')}>
            <i className="status-dot" />
            {bootLoading ? '连接服务中' : workspace.bootError ? '服务未连接' : '服务已连接'}
          </span>
          {capabilities && (
            <details className="status-pill status-trust">
              <summary>
                模型与来源
                <Icon name="chevron" size={10} className="trust-chev" />
              </summary>
              <div className="trust-pop">
                <p>{dataModeText(capabilities.data_mode)}</p>
                <p>{predictionMode(capabilities.prediction_mode)}</p>
                <p>{plannerMode(capabilities.llm_mode)}</p>
              </div>
            </details>
          )}
        </div>
        <HistoryMenu workspace={workspace} onLoad={loadRun} />
      </div>
    </header>

    <main id="workspace-main" className="workspace">
      <CommandPanel workspace={workspace} snapshot={snapshot} />
      <section className="stage" aria-label="评估结果">
        <RunBar workspace={workspace} run={run} onOpen={openDrawer} />
        <div className="stage-grid">
          <SnapshotCard snapshot={snapshot} loading={snapshotLoading && !run?.result} onOpen={openDrawer} />
          <PredictionCard run={run} busy={busy} task={task} onOpen={openDrawer} />
          <SummaryCard run={run} onOpen={openDrawer} />
        </div>
        <SimilarStrip run={run} busy={busy} task={task} onOpen={openDrawer} />
      </section>
    </main>

    <EvidenceDrawer run={run} snapshot={snapshot} capabilities={capabilities} open={workspace.traceOpen} view={view} onView={setView} onClose={closeDrawer} />
  </div>
}
