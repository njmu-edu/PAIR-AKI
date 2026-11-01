import type { CSSProperties, ReactNode } from 'react'

export type IconName = 'pulse' | 'arrow' | 'layers' | 'search' | 'clock' | 'check' | 'shield' | 'chevron' | 'refresh' | 'file' | 'alert' | 'close' | 'spark' | 'history' | 'link'

const paths: Record<IconName, ReactNode> = {
  pulse: <><path d="M3 12h4l3-7 4 14 3-7h4" /></>,
  arrow: <><path d="M4 12h16m-6-6 6 6-6 6" /></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  check: <path d="m5 12 4 4 10-10" />,
  shield: <><path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
  chevron: <path d="m8 5 7 7-7 7" />,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></>,
  file: <><path d="M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8M8 16h6" /></>,
  alert: <><path d="m12 3 10 18H2L12 3Zm0 6v5" /><circle cx="12" cy="17" r=".6" /></>,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z" /></>,
  history: <><path d="M3 4v5h5M3 9a9 9 0 1 1 0 6" /><path d="M12 7v5l4 2" /></>,
  link: <><path d="m10 13 4-4m-7 7-2 2a4 4 0 0 1-6-6" transform="translate(4 -1)" /><path d="m10 8 3-3a4 4 0 0 1 6 6l-3 3" /></>,
}

export function Icon({ name, size = 20, className = '', style }: { name: IconName; size?: number; className?: string; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className} style={style}>{paths[name]}</svg>
}

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}
