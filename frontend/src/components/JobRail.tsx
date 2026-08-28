import { CheckCircle2 } from 'lucide-react'
import { useDeferredValue } from 'react'
import { frameLabel } from '../lib/format'
import type { Job, JobStatus } from '../types'

type Filter = 'all' | 'active' | 'completed'

interface JobRailProps {
  jobs: Job[]
  selectedId: string | null
  filter: Filter
  onFilter: (filter: Filter) => void
  onSelect: (id: string) => void
}

const activeStatuses = new Set<JobStatus>(['queued', 'running'])

function statusLabel(job: Job) {
  if (job.status === 'running') return 'Active'
  if (job.status === 'interrupted') return 'Interrupted'
  return job.status.charAt(0).toUpperCase() + job.status.slice(1)
}

export function JobRail({ jobs, selectedId, filter, onFilter, onSelect }: JobRailProps) {
  const deferredFilter = useDeferredValue(filter)
  const visible = jobs.filter((job) => {
    if (deferredFilter === 'active') return activeStatuses.has(job.status)
    if (deferredFilter === 'completed') return job.status === 'completed'
    return true
  })
  return (
    <aside className="job-rail">
      <h2>Render jobs</h2>
      <div className="filter-tabs" aria-label="Filter render jobs">
        {(['all', 'active', 'completed'] as Filter[]).map((value) => (
          <button key={value} className={filter === value ? 'is-selected' : ''} onClick={() => onFilter(value)}>
            {value.charAt(0).toUpperCase() + value.slice(1)}
          </button>
        ))}
      </div>
      <div className="job-list">
        {visible.map((job) => (
          <button
            key={job.id}
            className={`job-row${job.id === selectedId ? ' is-selected' : ''}`}
            onClick={() => onSelect(job.id)}
          >
            <span className="job-row__top">
              <strong>{job.filename}</strong>
              <span className={`status-text status-text--${job.status}`}>{statusLabel(job)}</span>
            </span>
            <span className="job-row__bottom">
              <span>{frameLabel(job)}</span>
              {job.status === 'running' ? <strong>{Math.round(job.progress)}%</strong> : null}
              {job.status === 'completed' ? <CheckCircle2 size={19} /> : null}
            </span>
          </button>
        ))}
        {!visible.length ? <p className="job-list__empty">No jobs in this view.</p> : null}
      </div>
    </aside>
  )
}

