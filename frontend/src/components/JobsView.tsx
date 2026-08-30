import { Download, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { Fragment, type KeyboardEvent, useState } from 'react'
import { api } from '../lib/api'
import { formatDuration } from '../lib/format'
import type { Job, Scene } from '../types'

interface JobsViewProps {
  jobs: Job[]
  scenes: Scene[]
  podId: string | null
  onCancel: (job: Job) => Promise<void>
  onRetry: (job: Job) => Promise<void>
  onDelete: (job: Job) => Promise<void>
}

export function JobsView({ jobs, scenes, podId, onCancel, onRetry, onDelete }: JobsViewProps) {
  const sceneNames = new Map(scenes.map((scene) => [scene.id, scene.filename]))
  const [selectedId, setSelectedId] = useState<string | null>(null)

  function selectJob(jobId: string) {
    setSelectedId((current) => current === jobId ? null : jobId)
  }

  function selectJobWithKeyboard(event: KeyboardEvent<HTMLTableRowElement>, jobId: string) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      selectJob(jobId)
    }
  }

  return (
    <main className="jobs-view">
      <section className="jobs-table">
        <header>
          <div><h1>Jobs</h1><p>Shared execution history across connected pods.</p></div>
          <strong>{jobs.length}</strong>
        </header>
        <div className="job-table-scroll">
          <table>
            <thead><tr><th>Scene</th><th>Frames</th><th>Status</th><th>Progress</th><th>Backend</th><th>Pod</th><th>Elapsed</th><th /></tr></thead>
            <tbody>{jobs.map((job) => {
              const local = job.owner_pod_id === podId
              const recoverable = ['failed', 'canceled', 'interrupted'].includes(job.status)
              const selected = job.id === selectedId
              const detailHeading = job.status === 'failed' ? 'Failure details' : 'Job details'
              return <Fragment key={job.id}>
                <tr
                  aria-expanded={selected}
                  aria-selected={selected}
                  className={`job-table__row${selected ? ' is-selected' : ''}`}
                  onClick={() => selectJob(job.id)}
                  onKeyDown={(event) => selectJobWithKeyboard(event, job.id)}
                  tabIndex={0}
                >
                  <td>{sceneNames.get(job.scene_id) ?? job.filename}</td>
                  <td>{job.frame_start === job.frame_end ? job.frame_start : `${job.frame_start}–${job.frame_end}`}</td>
                  <td><span className={`job-status job-status--${job.status}`}>{job.owner_online ? job.status : 'owner offline'}</span></td>
                  <td><div className="table-progress"><span style={{ width: `${job.progress}%` }} /></div>{Math.round(job.progress)}%</td>
                  <td>{job.backend}</td>
                  <td>{job.owner_pod_id}</td>
                  <td>{formatDuration(job.elapsed_seconds)}</td>
                  <td>
                    <div className="job-actions" onClick={(event) => event.stopPropagation()}>
                      {job.status === 'completed' ? <button className="icon-button" title="Download job results" onClick={() => void api.downloadJobArchive(job)}><Download size={17} /></button> : null}
                      {local && (job.status === 'queued' || job.status === 'running') ? <button className="icon-button" title="Cancel" onClick={() => void onCancel(job)}><XCircle size={17} /></button> : null}
                      {local && recoverable ? <button className="icon-button" title="Retry" onClick={() => void onRetry(job)}><RefreshCw size={17} /></button> : null}
                      {local && ['completed', 'failed', 'canceled', 'interrupted'].includes(job.status) ? <button className="icon-button" title="Delete" onClick={() => void onDelete(job)}><Trash2 size={17} /></button> : null}
                      {!local ? <small>Read-only</small> : null}
                    </div>
                  </td>
                </tr>
                {selected ? <tr className="job-details-row"><td colSpan={8}>
                  <section className="job-details" aria-label={`${detailHeading} for ${job.filename}`}>
                    <div>
                      <h2>{detailHeading}</h2>
                      <p><strong>Job ID:</strong> {job.id}</p>
                    </div>
                    {job.status === 'failed' ? <div className="job-failure-reason">
                      <strong>Reason</strong>
                      <p>{job.error ?? 'The renderer did not report a specific reason. Review the log below.'}</p>
                    </div> : null}
                    {job.log_tail ? <pre className="job-log">{job.log_tail}</pre> : null}
                  </section>
                </td></tr> : null}
              </Fragment>
            })}</tbody>
          </table>
        </div>
      </section>
    </main>
  )
}
