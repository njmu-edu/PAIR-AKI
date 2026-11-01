import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { isTerminal } from './types'
import type { Capabilities, ComparisonMode, Run, Snapshot, TaskType } from './types'
import { taskGoals } from './v2'

const historyKey = 'pedaki-competition-run-ids-v2'
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '读取失败，请稍后重试。'

function savedRuns(): string[] {
  try {
    const data: unknown = JSON.parse(sessionStorage.getItem(historyKey) || '[]')
    return Array.isArray(data) ? data.filter((item): item is string => typeof item === 'string').slice(0, 12) : []
  } catch { return [] }
}

export function useWorkspace() {
  const [cases, setCases] = useState<Snapshot[]>([])
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [bootLoading, setBootLoading] = useState(true)
  const [bootError, setBootError] = useState('')
  const [bootAttempt, setBootAttempt] = useState(0)
  const [selectedRef, setSelectedRef] = useState('')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [snapshotLoading, setSnapshotLoading] = useState(false)
  const [snapshotError, setSnapshotError] = useState('')
  const [snapshotAttempt, setSnapshotAttempt] = useState(0)
  const [task, setTask] = useState<TaskType>('combined')
  const [goal, setGoal] = useState(taskGoals.combined)
  const [mode, setMode] = useState<ComparisonMode>('domain_agent')
  const [run, setRun] = useState<Run | null>(null)
  const [activeId, setActiveId] = useState('')
  const [readingRun, setReadingRun] = useState(false)
  const [runAttempt, setRunAttempt] = useState(0)
  const [runError, setRunError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [history, setHistory] = useState(savedRuns)
  const [historyView, setHistoryView] = useState(false)
  const submittingRef = useRef(false)
  const [traceOpen, setTraceOpen] = useState(false)

  const remember = useCallback((id: string) => {
    setHistory((current) => {
      const updated = [id, ...current.filter((item) => item !== id)].slice(0, 12)
      try { sessionStorage.setItem(historyKey, JSON.stringify(updated)) } catch { /* Optional local navigation only. */ }
      return updated
    })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setBootLoading(true)
    setBootError('')
    Promise.all([api.cases(controller.signal), api.capabilities(controller.signal)])
      .then(([items, info]) => {
        if (controller.signal.aborted) return
        setCases(items)
        setCapabilities(info)
        setSelectedRef((current) => current || items[0]?.case_ref || '')
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setBootError(errorMessage(error)) })
      .finally(() => { if (!controller.signal.aborted) setBootLoading(false) })
    return () => controller.abort()
  }, [bootAttempt])

  useEffect(() => {
    if (!selectedRef) return
    const controller = new AbortController()
    setSnapshot(null)
    setSnapshotLoading(true)
    setSnapshotError('')
    api.snapshot(selectedRef, controller.signal)
      .then((item) => {
        if (!controller.signal.aborted) setSnapshot(item)
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setSnapshotError(errorMessage(error)) })
      .finally(() => { if (!controller.signal.aborted) setSnapshotLoading(false) })
    return () => controller.abort()
  }, [selectedRef, snapshotAttempt])

  useEffect(() => {
    if (!activeId) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    setReadingRun(true)
    setRunError('')
    const poll = async () => {
      try {
        const item = await api.run(activeId, controller.signal)
        if (controller.signal.aborted) return
        setRun(item)
        setSelectedRef(item.request.case_ref)
        setTask(item.request.task)
        setMode(item.request.mode)
        setGoal(item.request.goal)
        remember(item.run_id)
        if (isTerminal(item.status)) {
          setReadingRun(false)
        } else {
          timer = setTimeout(() => { void poll() }, 1200)
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          setReadingRun(false)
          setRunError(errorMessage(error))
        }
      }
    }
    void poll()
    return () => { controller.abort(); if (timer) clearTimeout(timer) }
  }, [activeId, runAttempt, remember])

  const clearResult = () => {
    setRun(null)
    setActiveId('')
    setRunError('')
    setTraceOpen(false)
    setHistoryView(false)
  }
  const busy = submitting || readingRun || Boolean(run && !isTerminal(run.status))

  const chooseCase = (id: string) => {
    if (busy) return
    clearResult()
    setSelectedRef(id)
  }
  const chooseTask = (value: TaskType) => {
    if (busy || value === task) return
    clearResult()
    setTask(value)
    setGoal(taskGoals[value])
  }
  const chooseMode = (value: ComparisonMode) => {
    if (busy || value === mode) return
    clearResult()
    setMode(value)
  }

  const start = async () => {
    if (!snapshot || snapshotLoading || busy || historyView || submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    clearResult()
    try {
      const id = await api.start({ case_ref: snapshot.case_ref, snapshot_ref: snapshot.snapshot_ref, task, mode, goal })
      remember(id)
      setActiveId(id)
    } catch (error) {
      setRunError(`${errorMessage(error)} 提交未确认，请核对服务记录，避免重复启动。`)
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const loadRun = (id: string) => {
    if (busy || !id.trim()) return
    setRun(null)
    setRunError('')
    setReadingRun(true)
    setHistoryView(true)
    setActiveId(id.trim())
    setRunAttempt((value) => value + 1)
    setTraceOpen(true)
  }

  return {
    cases, capabilities, bootLoading, bootError, retryBoot: () => setBootAttempt((value) => value + 1),
    snapshot, selectedRef, snapshotLoading, snapshotError, retrySnapshot: () => setSnapshotAttempt((value) => value + 1),
    task, goal, chooseGoal: (value: string) => { if (!busy) { clearResult(); setGoal(value) } }, mode, run, activeId, busy, submitting, readingRun, runError, history, historyView, traceOpen, setTraceOpen,
    chooseCase, chooseTask, chooseMode, start, loadRun, leaveHistory: clearResult, retryRun: () => setRunAttempt((value) => value + 1),
  }
}

export type Workspace = ReturnType<typeof useWorkspace>
