import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { demoJobs, demoResourceHistory, demoSystem } from '../lib/demo'
import { deserializeResourceHistory, type ResourceSample } from '../lib/resourceHistory'
import type { Job, RenderForm, SystemInfo } from '../types'
import { AppHeader } from './AppHeader'
import { JobRail } from './JobRail'
import { NewRenderPanel } from './NewRenderPanel'
import { RenderWorkspace } from './RenderWorkspace'
import { SystemPanel } from './SystemPanel'

type Filter = 'all' | 'active' | 'completed'
type SidePanel = 'new-render' | 'system' | null

interface DashboardProps {
  demo: boolean
  onLogout: () => Promise<void>
}

export function Dashboard({ demo, onLogout }: DashboardProps) {
  const [jobs, setJobs] = useState<Job[]>(demo ? demoJobs : [])
  const [system, setSystem] = useState<SystemInfo | null>(demo ? demoSystem : null)
  const [resourceHistory, setResourceHistory] = useState<ResourceSample[]>(demo ? demoResourceHistory : [])
  const [selectedId, setSelectedId] = useState<string | null>(demo ? demoJobs[0].id : null)
  const [filter, setFilter] = useState<Filter>('all')
  const [sidePanel, setSidePanel] = useState<SidePanel>('new-render')
  const [queueing, setQueueing] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    if (demo) return
    try {
      const [nextJobs, nextSystem, nextTelemetry] = await Promise.all([
        api.jobs(),
        api.system(),
        api.telemetry(),
      ])
      setJobs(nextJobs)
      setSystem(nextSystem)
      setResourceHistory(deserializeResourceHistory(nextTelemetry))
      setSelectedId((current) => current && nextJobs.some((job) => job.id === current) ? current : nextJobs[0]?.id ?? null)
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to refresh render node')
    }
  }, [demo])

  const hasActiveJobs = jobs.some((job) => job.status === 'running' || job.status === 'queued')

  useEffect(() => {
    if (demo) return
    let canceled = false
    let timer: number | undefined
    async function poll() {
      await refresh()
      if (!canceled) {
        timer = window.setTimeout(poll, hasActiveJobs ? 1500 : 8000)
      }
    }
    void poll()
    return () => {
      canceled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [demo, hasActiveJobs, refresh])

  const selectedJob = jobs.find((job) => job.id === selectedId) ?? null
  const latestSample = resourceHistory.length ? resourceHistory[resourceHistory.length - 1] : null

  async function createJob(form: RenderForm) {
    if (demo) return
    setQueueing(true)
    try {
      const job = await api.createJob(form)
      setJobs((current) => [job, ...current])
      setSelectedId(job.id)
    } finally {
      setQueueing(false)
    }
  }

  async function applyJobAction(job: Job, action: (id: string) => Promise<Job>) {
    if (demo) return
    const updated = await action(job.id)
    setJobs((current) => current.map((item) => item.id === updated.id ? updated : item))
  }

  async function deleteJob(job: Job) {
    if (demo || !window.confirm(`Delete ${job.filename} and all rendered frames?`)) return
    await api.delete(job.id)
    setJobs((current) => current.filter((item) => item.id !== job.id))
  }

  return (
    <div className={`app-shell${sidePanel ? ' app-shell--panel-open' : ''}`}>
      <AppHeader system={system} latestSample={latestSample} renderPanelOpen={sidePanel === 'new-render'} systemPanelOpen={sidePanel === 'system'} onOpenPanel={() => setSidePanel('new-render')} onOpenSystem={() => setSidePanel('system')} onLogout={() => void onLogout()} />
      {error ? <div className="global-error" role="alert">{error}</div> : null}
      <div className="app-body">
        <JobRail jobs={jobs} selectedId={selectedId} filter={filter} onFilter={setFilter} onSelect={setSelectedId} />
        <RenderWorkspace job={selectedJob} demo={demo} onCancel={(job) => applyJobAction(job, api.cancel)} onRetry={(job) => applyJobAction(job, api.retry)} onDelete={deleteJob} />
        <NewRenderPanel open={sidePanel === 'new-render'} system={system} busy={queueing} onClose={() => setSidePanel(null)} onSubmit={createJob} />
        <SystemPanel open={sidePanel === 'system'} system={system} samples={resourceHistory} onClose={() => setSidePanel(null)} />
      </div>
    </div>
  )
}
