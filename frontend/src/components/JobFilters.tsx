import { Filter, RotateCcw } from 'lucide-react'
import { useMemo } from 'react'
import type { Backend, Job, JobStatus, Scene } from '../types'

export interface JobFilters {
  sceneId: string
  status: JobStatus | ''
  backend: Backend | ''
  podId: string
}

interface JobFiltersProps {
  jobs: Job[]
  scenes: Scene[]
  filters: JobFilters
  onChange: (filters: JobFilters) => void
}

const statuses: JobStatus[] = ['queued', 'running', 'completed', 'failed', 'canceled', 'interrupted']
const backends: Backend[] = ['OPTIX', 'CUDA', 'CPU']

export function JobFilters({ jobs, scenes, filters, onChange }: JobFiltersProps) {
  const options = useMemo(() => {
    const sceneNames = new Map(scenes.map((scene) => [scene.id, scene.filename]))
    const sceneIds = new Set<string>()
    const jobStatuses = new Set<JobStatus>()
    const jobBackends = new Set<Backend>()
    const podIds = new Set<string>()

    for (const job of jobs) {
      sceneIds.add(job.scene_id)
      jobStatuses.add(job.status)
      jobBackends.add(job.backend)
      podIds.add(job.owner_pod_id)
    }

    return {
      scenes: [...sceneIds]
        .map((id) => ({ id, name: sceneNames.get(id) ?? jobs.find((job) => job.scene_id === id)?.filename ?? id }))
        .sort((left, right) => left.name.localeCompare(right.name)),
      statuses: statuses.filter((status) => jobStatuses.has(status)),
      backends: backends.filter((backend) => jobBackends.has(backend)),
      podIds: [...podIds].sort(),
    }
  }, [jobs, scenes])
  const hasFilters = Object.values(filters).some(Boolean)

  return (
    <aside className="jobs-sidebar" aria-label="Job filters">
      <header className="jobs-sidebar__heading"><Filter size={18} /><h2>Filters</h2></header>
      <label className="jobs-filter">
        <span>Scene</span>
        <select value={filters.sceneId} onChange={(event) => onChange({ ...filters, sceneId: event.target.value })}>
          <option value="">All scenes</option>
          {options.scenes.map((scene) => <option key={scene.id} value={scene.id}>{scene.name}</option>)}
        </select>
      </label>
      <label className="jobs-filter">
        <span>Status</span>
        <select value={filters.status} onChange={(event) => onChange({ ...filters, status: event.target.value as JobStatus | '' })}>
          <option value="">All statuses</option>
          {options.statuses.map((status) => <option key={status} value={status}>{status}</option>)}
        </select>
      </label>
      <label className="jobs-filter">
        <span>Backend</span>
        <select value={filters.backend} onChange={(event) => onChange({ ...filters, backend: event.target.value as Backend | '' })}>
          <option value="">All backends</option>
          {options.backends.map((backend) => <option key={backend} value={backend}>{backend}</option>)}
        </select>
      </label>
      <label className="jobs-filter">
        <span>Pod</span>
        <select value={filters.podId} onChange={(event) => onChange({ ...filters, podId: event.target.value })}>
          <option value="">All pods</option>
          {options.podIds.map((podId) => <option key={podId} value={podId}>{podId}</option>)}
        </select>
      </label>
      <button className="button button--subtle jobs-filter-reset" onClick={() => onChange({ sceneId: '', status: '', backend: '', podId: '' })} disabled={!hasFilters}>
        <RotateCcw size={15} /> Clear filters
      </button>
    </aside>
  )
}
