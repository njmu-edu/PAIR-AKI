import { useEffect, useRef, useState } from 'react'
import type { Workspace } from '../useWorkspace'
import { Icon } from './Icon'

export function HistoryMenu({ workspace, onLoad }: { workspace: Workspace; onLoad: (id: string) => void }) {
  const [input, setInput] = useState('')
  const ref = useRef<HTMLDetailsElement>(null)
  const { busy, history } = workspace

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const menu = ref.current
      if (menu?.open && !menu.contains(event.target as Node)) menu.open = false
    }
    const onKey = (event: KeyboardEvent) => {
      const menu = ref.current
      if (event.key === 'Escape' && menu?.open) { menu.open = false; menu.querySelector('summary')?.focus() }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('pointerdown', onPointerDown); document.removeEventListener('keydown', onKey) }
  }, [])

  const load = (id: string) => {
    onLoad(id)
    if (ref.current) ref.current.open = false
  }

  return <details className="history-menu" ref={ref}>
    <summary><Icon name="history" size={15} />运行记录</summary>
    <div className="history-popover">
      <h3>读回已保存的运行</h3>
      <p>只保存本次浏览器会话的运行编号，结果从服务端读取。</p>
      <form onSubmit={(event) => { event.preventDefault(); load(input) }}>
        <label htmlFor="run-reference">运行编号</label>
        <div className="history-input-row">
          <input id="run-reference" value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入 run_id" maxLength={180} autoComplete="off" disabled={busy} />
          <button className="ghost-button" type="submit" disabled={busy || !input.trim()}>读取</button>
        </div>
      </form>
      {history.length > 0
        ? <ul>{history.map((id) => <li key={id}><button onClick={() => load(id)} disabled={busy}><code>{id}</code><Icon name="arrow" size={14} /></button></li>)}</ul>
        : <div className="history-empty">完成第一次评估后，运行编号将出现在这里。</div>}
    </div>
  </details>
}
