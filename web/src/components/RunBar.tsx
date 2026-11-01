import type { DrawerView, Run } from '../types'
import type { Workspace } from '../useWorkspace'
import { cx } from '../cx'
import { eventLabel, statusLabel, toolLabel } from '../format'
import { Icon, Spinner } from './Icon'

export function RunBar({ workspace, run, onOpen }: { workspace: Workspace; run: Run | null; onOpen: (view: DrawerView) => void }) {
  const { busy, bootLoading, bootError, snapshotError, runError, activeId, cases } = workspace
  const lastEvent = run?.events.at(-1)
  const actions = run && <div className="runbar-actions">
    <button className="ghost-button" onClick={() => onOpen({ tab: 'summary' })}><Icon name="file" size={14} />说明与限制</button>
    <button className="ghost-button" onClick={() => onOpen({ tab: 'trace' })}><Icon name="layers" size={14} />过程与证据</button>
  </div>

  const retry = (text: string, handler: (() => void) | undefined, label: string) => <div className="runbar status-failed" role="alert">
    <span className="runbar-state"><Icon name="alert" size={17} /><strong>{text}</strong></span>
    {handler && <button className="ghost-button" onClick={handler}><Icon name="refresh" size={14} />{label}</button>}
  </div>

  if (bootError) return retry(bootError, workspace.retryBoot, '重新连接')
  if (snapshotError) return retry(snapshotError, workspace.retrySnapshot, '重新读取')
  if (runError) return retry(runError + (activeId ? ' 运行编号：' + activeId + '。重新读取不会重复启动任务。' : ''), activeId ? workspace.retryRun : undefined, '重新读取')

  if (run || workspace.submitting || workspace.readingRun) {
    const status = run?.status || 'running'
    return <div className={cx('runbar', 'status-' + status)} role="status" aria-live="polite">
      <span className="runbar-state">
        {busy ? <Spinner /> : <Icon name={status === 'succeeded' ? 'check' : 'alert'} size={17} />}
        <strong>{workspace.submitting ? '提交评估任务' : run ? statusLabel(run.status) : '正在读取运行记录'}</strong>
        <span className="runbar-detail">{lastEvent ? lastEvent.reason || eventLabel(lastEvent.kind) + (lastEvent.tool ? ' · ' + toolLabel(lastEvent.tool) : '') : '等待服务端反馈'}</span>
      </span>
      {actions}
    </div>
  }

  return <div className="runbar status-idle" role="status">
    <span className="runbar-state">
      {bootLoading ? <Spinner /> : <Icon name="spark" size={17} />}
      <strong>{bootLoading ? '正在连接服务' : cases.length ? '准备就绪' : '暂无可用病例'}</strong>
      <span className="runbar-detail">{bootLoading ? '读取病例与能力信息' : cases.length ? '选择病例与任务，点击“开始”获得评估' : '请由服务端提供合格的病例后重新连接'}</span>
    </span>
  </div>
}
