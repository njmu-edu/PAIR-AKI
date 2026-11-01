import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { Observation } from '../types'
import { cx } from '../cx'
import { number } from '../format'
import { Icon } from './Icon'

const normalizedUnit = (unit: string) => unit.replace('μ', 'u').replace('µ', 'u').toLowerCase()
const usable = (item: Observation) => item.status === 'known' && item.value !== null && Number.isFinite(item.value) && Number.isFinite(item.event_hours)

function usePlotBox() {
  const ref = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const update = () => setBox({ w: Math.round(element.clientWidth), h: Math.round(element.clientHeight) })
    update()
    const frame = requestAnimationFrame(update)
    const observer = new ResizeObserver(update)
    observer.observe(element)
    window.addEventListener('resize', update)
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener('resize', update) }
  }, [])
  return [ref, box] as const
}

export function TrendChart({ observations, comparison, compact = false, label = '肌酐变化' }: { observations: Observation[]; comparison?: Observation[]; compact?: boolean; label?: string }) {
  const id = useId().replaceAll(':', '')
  const [plotRef, box] = usePlotBox()
  const points = observations.filter(usable).sort((a, b) => a.event_hours - b.event_hours)
  const comparisonPoints = (comparison || []).filter(usable).sort((a, b) => a.event_hours - b.event_hours)
  const allPoints = [...points, ...comparisonPoints]
  const units = new Set(allPoints.map((item) => normalizedUnit(item.unit)))
  const drawable = points.length > 0 && units.size === 1
  const { w: width, h: height } = box

  let svg = null
  if (drawable && width > 60 && height > 50) {
    const padding = { left: compact ? 32 : 42, right: 12, top: 12, bottom: compact ? 20 : 24 }
    const values = allPoints.map((point) => point.value as number)
    const xMin = Math.min(-24, ...allPoints.map((point) => point.event_hours))
    const xMax = Math.max(0, ...allPoints.map((point) => point.event_hours))
    const yMin = Math.max(0, Math.floor(Math.min(...values) / 10) * 10 - 10)
    const yMax = Math.ceil(Math.max(...values) / 10) * 10 + 10
    const plotWidth = width - padding.left - padding.right
    const plotHeight = height - padding.top - padding.bottom
    const x = (hours: number) => padding.left + ((hours - xMin) / (xMax - xMin || 1)) * plotWidth
    const y = (value: number) => height - padding.bottom - ((value - yMin) / (yMax - yMin || 1)) * plotHeight
    const path = (list: Observation[]) => list.map((point, index) => (index === 0 ? 'M' : 'L') + ' ' + x(point.event_hours) + ' ' + y(point.value as number)).join(' ')
    const line = path(points)
    const area = line + ' L ' + x(points[points.length - 1].event_hours) + ' ' + (height - padding.bottom) + ' L ' + x(points[0].event_hours) + ' ' + (height - padding.bottom) + ' Z'
    const yTicks = height < 110 ? [yMin, yMax] : [yMin, (yMin + yMax) / 2, yMax]
    const xTicks = width < 220 ? [xMin, 0] : [xMin, xMin / 2, 0]
    const description = points.map((point) => '距评估时点' + number(point.event_hours) + '小时：' + number(point.value) + ' ' + point.unit).join('；')
      + '。' + (comparisonPoints.length > 0 ? '虚线为当前病例：' + comparisonPoints.map((point) => number(point.event_hours) + '小时，' + number(point.value) + ' ' + point.unit).join('；') + '。' : '')
      + '仅展示已知且有数值的观测，曲线连线不代表中间时刻有测量。'
    svg = <svg width={width} height={height} viewBox={'0 0 ' + width + ' ' + height} preserveAspectRatio="none" role="img" aria-labelledby={'title-' + id + ' desc-' + id}>
      <title id={'title-' + id}>{label}</title>
      <desc id={'desc-' + id}>{description}</desc>
      <defs><linearGradient id={'area-' + id} x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#14b8b0" stopOpacity=".28" /><stop offset="100%" stopColor="#14b8b0" stopOpacity="0" /></linearGradient></defs>
      {yTicks.map((value) => <g key={value}><line x1={padding.left} x2={width - padding.right} y1={y(value)} y2={y(value)} stroke="#e1ecec" strokeDasharray="3 5" /><text x={padding.left - 8} y={y(value) + 4} textAnchor="end" className="chart-tick">{number(value, 0)}</text></g>)}
      <line x1={x(0)} x2={x(0)} y1={padding.top} y2={height - padding.bottom} stroke="#7fb4b9" strokeDasharray="4 4" />
      <path d={area} fill={'url(#area-' + id + ')'} />
      {comparisonPoints.length > 0 && <path d={path(comparisonPoints)} fill="none" stroke="#8aa0a8" strokeWidth="1.6" strokeDasharray="4 4" strokeLinecap="round" />}
      <path d={line} fill="none" stroke="#0a7a82" strokeWidth={compact ? 2 : 2.6} strokeLinejoin="round" strokeLinecap="round" />
      {points.map((point, index) => <circle key={point.ref + '-' + index} cx={x(point.event_hours)} cy={y(point.value as number)} r={compact ? 2.8 : 3.8} fill="#fff" stroke="#0a7a82" strokeWidth="2"><title>{point.ref} · {number(point.event_hours)} h · {number(point.value)} {point.unit}</title></circle>)}
      {xTicks.map((value) => <text key={value} x={x(value)} y={height - 5} textAnchor={value === 0 ? 'end' : 'middle'} className="chart-tick">{value === 0 ? '评估时点' : number(value, 0) + ' h'}</text>)}
    </svg>
  }

  return <div className={cx('trend', compact && 'compact')}>
    <div className="trend-plot" ref={plotRef}>
      {drawable ? svg : <div className="chart-empty"><Icon name="pulse" size={18} /><span>{units.size > 1 ? '记录单位不一致，暂不绘制共同曲线' : '暂无可绘制的合格观测'}</span></div>}
    </div>
    {drawable && <div className="chart-caption">
      {comparisonPoints.length > 0 && <span><i className="legend-line" />当前病例</span>}
      <span><i className="legend-dot" />{comparisonPoints.length > 0 ? '参考病例' : '肌酐'} · {points[0].unit}</span>
      {!compact && <span className="caption-note">相对评估时点 · 连线仅辅助阅读</span>}
    </div>}
  </div>
}

export function ObservationTable({ observations }: { observations: Observation[] }) {
  if (!observations.length) return <p className="muted">暂无观测记录。</p>
  return <div className="table-scroll"><table><thead><tr><th scope="col">来源引用</th><th scope="col">相对时点</th><th scope="col">数值</th><th scope="col">状态</th></tr></thead><tbody>{observations.map((item, index) => <tr key={item.ref + '-' + index}><td className="mono">{item.ref}</td><td>{number(item.event_hours)} h</td><td>{number(item.value)} {item.unit}</td><td>{item.status === 'conflict' ? '存在冲突' : '已知'}</td></tr>)}</tbody></table></div>
}
