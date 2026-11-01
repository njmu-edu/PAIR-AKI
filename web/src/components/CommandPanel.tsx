import type { ComparisonMode, Snapshot } from '../types'
import type { Workspace } from '../useWorkspace'
import { date, taskLabel } from '../format'
import { Icon, Spinner } from './Icon'
import { TaskPicker } from './TaskPicker'

export function CommandPanel({ workspace, snapshot }: { workspace: Workspace; snapshot: Snapshot | null }) {
  const { busy, bootLoading, snapshotLoading, run, task, historyView, cases, selectedRef } = workspace
  const startDisabled = busy || bootLoading || (!historyView && (!snapshot || snapshotLoading || !workspace.goal.trim() || Boolean(workspace.bootError || workspace.snapshotError)))
  const ctaLabel = workspace.submitting ? '正在提交任务' : busy ? '评估进行中' : historyView ? '返回当前病例状态' : '开始' + taskLabel(task)
  return <section className="command" aria-labelledby="command-heading">
    <h1 id="command-heading" className="sr-only">PAIR-AKI｜肾见 发起评估</h1>
    <div className="command-row select-row">
      <div className="field">
        <label htmlFor="case-select">当前病例</label>
        <div className="select-wrap">
          <select id="case-select" value={selectedRef} onChange={(event) => workspace.chooseCase(event.target.value)} disabled={busy || bootLoading || !cases.length}>
            <option value="" disabled>{bootLoading ? '正在读取病例…' : '请选择病例'}</option>
            {cases.map((item) => <option key={item.case_ref + '-' + item.snapshot_ref} value={item.case_ref}>{item.label}</option>)}
            {selectedRef && !cases.some((item) => item.case_ref === selectedRef) && <option value={selectedRef}>{snapshot?.label || selectedRef}（历史运行）</option>}
          </select>
        </div>
      </div>
      <div className="field">
        <span className="field-label">评估时点 <em>北京时间</em></span>
        <div className="time-box">
          <Icon name="clock" size={16} />
          <strong>{snapshotLoading && !run?.result ? '读取中…' : date(snapshot?.decision_time)}</strong>
        </div>
      </div>
      <div className="field">
        <span className="field-label">评估任务</span>
        <TaskPicker value={task} disabled={busy} onChange={workspace.chooseTask} />
      </div>
    </div>

    <div className="command-row goal-row">
      <div className="field goal-field">
        <div className="goal-head">
          <label htmlFor="assessment-goal">评估目标</label>
          <details className="settings">
            <summary>运行设置 <Icon name="chevron" size={12} /></summary>
            <div className="settings-pop">
              <label htmlFor="comparison-mode">执行方式</label>
              <select id="comparison-mode" value={workspace.mode} onChange={(event) => workspace.chooseMode(event.target.value as ComparisonMode)} disabled={busy}>
                <option value="domain_agent">任务驱动 Agent</option>
                <option value="general_agent">通用工具 Agent 对照</option>
                <option value="fixed">固定流程对照</option>
              </select>
              <p>对照模式沿用服务端相同工具与输入权限，具体调用见执行记录。</p>
            </div>
          </details>
        </div>
        <textarea id="assessment-goal" rows={2} value={workspace.goal} onChange={(event) => workspace.chooseGoal(event.target.value)} disabled={busy} maxLength={2000} />
      </div>
      <div className="command-actions">
        <button className="cta" onClick={() => historyView ? workspace.leaveHistory() : void workspace.start()} disabled={startDisabled}>
          {busy && <Spinner />}
          <span>{ctaLabel}</span>
          {!busy && <Icon name="arrow" size={17} />}
        </button>
      </div>
    </div>
    <p className="safety-note">{historyView ? '正在查看已保存的运行' : '仅使用评估时点可用的病例信息'}。科研用途，需专业人员审阅，不替代临床判断。</p>
  </section>
}
