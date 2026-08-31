import { Activity, FileUp, LogOut, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { deserializeResourceHistory, type ResourceSample } from '../lib/resourceHistory'
import type { CreateJobForm, FrameGroup, Job, Scene, SystemInfo, UploadProgress } from '../types'
import { Brand } from './Brand'
import { JobFilters as JobFiltersSidebar, type JobFilters } from './JobFilters'
import { JobsView } from './JobsView'
import { NewJobPanel } from './NewJobPanel'
import { SceneRail } from './SceneRail'
import { SceneWorkspace } from './SceneWorkspace'
import { SystemPanel } from './SystemPanel'
import { UploadScenePanel } from './UploadScenePanel'

type View = 'scenes' | 'jobs'
type Panel = 'upload' | 'job' | null

const emptyJobFilters: JobFilters = { sceneId: '', status: '', backend: '', podId: '' }

interface DashboardProps { onLogout: () => Promise<void> }

export function Dashboard({ onLogout }: DashboardProps) {
  const [view, setView] = useState<View>('scenes')
  const [panel, setPanel] = useState<Panel>(null)
  const [scenes, setScenes] = useState<Scene[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [jobFilters, setJobFilters] = useState<JobFilters>(emptyJobFilters)
  const [frames, setFrames] = useState<FrameGroup[]>([])
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null)
  const [system, setSystem] = useState<SystemInfo | null>(null)
  const [resourceHistory, setResourceHistory] = useState<ResourceSample[]>([])
  const [busy, setBusy] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null)
  const [systemPanelOpen, setSystemPanelOpen] = useState(false)
  const [error, setError] = useState('')
  const uploadAbortRef = useRef<AbortController | null>(null)
  const uploadIdRef = useRef<string | null>(null)

  const selectedScene = scenes.find((scene) => scene.id === selectedSceneId) ?? null
  const selectedJobs = useMemo(() => jobs.filter((job) => job.scene_id === selectedSceneId), [jobs, selectedSceneId])
  const filteredJobs = useMemo(() => jobs.filter((job) => (
    (!jobFilters.sceneId || job.scene_id === jobFilters.sceneId)
    && (!jobFilters.status || job.status === jobFilters.status)
    && (!jobFilters.backend || job.backend === jobFilters.backend)
    && (!jobFilters.podId || job.owner_pod_id === jobFilters.podId)
  )), [jobFilters, jobs])
  const hasActive = jobs.some((job) => job.status === 'queued' || job.status === 'running')

  const refresh = useCallback(async () => {
    try {
      const [nextScenes, nextJobs, nextSystem, nextTelemetry] = await Promise.all([api.scenes(), api.jobs(), api.system(), api.telemetry()])
      setScenes(nextScenes); setJobs(nextJobs); setSystem(nextSystem); setResourceHistory(deserializeResourceHistory(nextTelemetry))
      setSelectedSceneId((current) => current && nextScenes.some((scene) => scene.id === current) ? current : nextScenes[0]?.id ?? null)
      setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to refresh workspace') }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), hasActive ? 1800 : 8000)
    return () => window.clearInterval(timer)
  }, [hasActive, refresh])
  useEffect(() => {
    if (!selectedSceneId) { setFrames([]); return }
    api.frames(selectedSceneId).then((page) => setFrames(page.items)).catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load scene results'))
  }, [selectedSceneId, jobs])

  async function uploadScene(file: File, name: string) {
    const controller = new AbortController()
    uploadAbortRef.current = controller
    setBusy(true); setUploadProgress({ loaded: 0, total: file.size, phase: 'uploading' })
    try {
      const scene = await api.uploadScene(file, name, {
        onProgress: setUploadProgress,
        onSession: (uploadId) => { uploadIdRef.current = uploadId },
        signal: controller.signal,
      })
      await refresh(); setSelectedSceneId(scene.id); setPanel('job')
    } finally {
      uploadAbortRef.current = null
      uploadIdRef.current = null
      setBusy(false)
      setUploadProgress(null)
    }
  }
  async function cancelUpload() {
    const uploadId = uploadIdRef.current
    uploadAbortRef.current?.abort()
    if (uploadId) {
      try { await api.deleteUpload(uploadId) } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Unable to cancel upload')
      }
    }
    setPanel(null)
  }
  async function createJob(form: CreateJobForm) { setBusy(true); try { await api.createJob(form); await refresh(); setPanel(null) } finally { setBusy(false) } }
  async function deleteScene(scene: Scene) { if (!window.confirm(`Delete ${scene.name}, all results, and terminal jobs?`)) return; await api.deleteScene(scene.id); await refresh() }
  async function updateJob(job: Job, action: (id: string) => Promise<Job>) { await action(job.id); await refresh() }
  async function deleteJob(job: Job) { if (!window.confirm(`Delete job ${job.id.slice(0, 8)}? Published scene results remain.`)) return; await api.deleteJob(job.id); await refresh() }
  const latest = resourceHistory.at(-1)

  return <div className="shared-app">
    <header className="shared-header"><Brand /><nav><button className={view === 'scenes' ? 'is-selected' : ''} onClick={() => setView('scenes')}>Scenes</button><button className={view === 'jobs' ? 'is-selected' : ''} onClick={() => setView('jobs')}>Jobs</button></nav><div className="header-actions"><button className={`system-meter${systemPanelOpen ? ' is-active' : ''}`} onClick={() => { setPanel(null); setSystemPanelOpen((open) => !open) }} aria-controls="system-panel" aria-expanded={systemPanelOpen} aria-label="Open performance panel"><Activity className="system-meter__icon" size={18} /><span className="system-meter__metric"><b>CPU</b><strong>{formatPercent(latest?.cpuUtilization)}</strong></span><span className="system-meter__metric"><b>GPU</b><strong>{formatPercent(latest?.gpuUtilization)}</strong></span><span className="system-meter__metric"><b>MEM</b><strong>{formatPercent(latest?.memoryUtilization)}</strong></span><span className="system-meter__metric"><b>POD</b><strong>{system?.pod_id ?? '—'}</strong></span></button><button className="button button--outline" onClick={() => { setSystemPanelOpen(false); setPanel('upload') }}><FileUp size={17} /> Upload scene</button><button className="button button--primary header-new-job" onClick={() => { setSystemPanelOpen(false); setPanel('job') }} disabled={!selectedScene}><Plus size={17} /> New render</button><button className="icon-button" onClick={() => void onLogout()} aria-label="Sign out"><LogOut size={18} /></button></div></header>
    {error ? <div className="global-error" role="alert">{error}</div> : null}
    <div className="shared-body">{view === 'scenes' ? <><SceneRail scenes={scenes} selectedId={selectedSceneId} onSelect={setSelectedSceneId} onUpload={() => setPanel('upload')} /><SceneWorkspace scene={selectedScene} frames={frames} jobs={selectedJobs} onDelete={deleteScene} /></> : <><JobFiltersSidebar jobs={jobs} scenes={scenes} filters={jobFilters} onChange={setJobFilters} /><JobsView jobs={filteredJobs} scenes={scenes} podId={system?.pod_id ?? null} onCancel={(job) => updateJob(job, api.cancel)} onRetry={(job) => updateJob(job, api.retry)} onDelete={deleteJob} /></>}</div>
    <UploadScenePanel open={panel === 'upload'} busy={busy} progress={uploadProgress} onClose={() => setPanel(null)} onCancel={cancelUpload} onUpload={uploadScene} />
    <NewJobPanel open={panel === 'job'} scene={selectedScene} system={system} busy={busy} onClose={() => setPanel(null)} onSubmit={createJob} />
    <SystemPanel open={systemPanelOpen} system={system} samples={resourceHistory} onClose={() => setSystemPanelOpen(false)} />
  </div>
}

function formatPercent(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value)}%`
}
