import { Download, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { api } from '../lib/api'
import { formatDuration } from '../lib/format'
import type { Job, Scene } from '../types'

interface JobsViewProps { jobs: Job[]; scenes: Scene[]; podId: string | null; onCancel: (job: Job) => Promise<void>; onRetry: (job: Job) => Promise<void>; onDelete: (job: Job) => Promise<void> }

export function JobsView({ jobs, scenes, podId, onCancel, onRetry, onDelete }: JobsViewProps) {
  const sceneNames = new Map(scenes.map((scene) => [scene.id, scene.filename]))
  return <main className="jobs-view"><section className="jobs-table"><header><div><h1>Jobs</h1><p>Shared execution history across connected pods.</p></div><strong>{jobs.length}</strong></header><div className="job-table-scroll"><table><thead><tr><th>Scene</th><th>Frames</th><th>Status</th><th>Progress</th><th>Backend</th><th>Pod</th><th>Elapsed</th><th /></tr></thead><tbody>{jobs.map((job) => {
    const local = job.owner_pod_id === podId
    const recoverable = ['failed', 'canceled', 'interrupted'].includes(job.status)
    return <tr key={job.id}><td>{sceneNames.get(job.scene_id) ?? job.filename}</td><td>{job.frame_start === job.frame_end ? job.frame_start : `${job.frame_start}–${job.frame_end}`}</td><td><span className={`job-status job-status--${job.status}`}>{job.owner_online ? job.status : 'owner offline'}</span></td><td><div className="table-progress"><span style={{ width: `${job.progress}%` }} /></div>{Math.round(job.progress)}%</td><td>{job.backend}</td><td>{job.owner_pod_id}</td><td>{formatDuration(job.elapsed_seconds)}</td><td><div className="job-actions">{job.status === 'completed' ? <button className="icon-button" title="Download job results" onClick={() => void api.downloadJobArchive(job)}><Download size={17} /></button> : null}{local && (job.status === 'queued' || job.status === 'running') ? <button className="icon-button" title="Cancel" onClick={() => void onCancel(job)}><XCircle size={17} /></button> : null}{local && recoverable ? <button className="icon-button" title="Retry" onClick={() => void onRetry(job)}><RefreshCw size={17} /></button> : null}{local && ['completed', 'failed', 'canceled', 'interrupted'].includes(job.status) ? <button className="icon-button" title="Delete" onClick={() => void onDelete(job)}><Trash2 size={17} /></button> : null}{!local ? <small>Read-only</small> : null}</div></td></tr>
  })}</tbody></table></div></section></main>
}
