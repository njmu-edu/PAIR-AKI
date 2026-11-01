import { Component, StrictMode } from 'react'
import type { ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

class DisplayBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <main className="display-error"><h1>页面暂时无法显示</h1><p>服务返回的数据未能正常呈现。已受理的任务仍可通过运行编号读回。</p><button onClick={() => window.location.reload()}>重新打开页面</button></main>
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(<StrictMode><DisplayBoundary><App /></DisplayBoundary></StrictMode>)
