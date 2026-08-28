import { AlertTriangle, Download, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { demoRenderUrl } from '../lib/demo'
import { formatDuration } from '../lib/format'
import type { Job } from '../types'

interface RenderWorkspaceProps {
  job: Job | null
  demo: boolean
  onCancel: (job: Job) => Promise<void>
  onRetry: (job: Job) => Promise<void>
  onDelete: (job: Job) => Promise<void>
}

function statusLine(job: Job) {
  if (job.status === 'running') return `Rendering frame ${job.current_frame ?? job.frame_start} of ${job.frame_end}`
  if (job.status === 'queued') return 'Waiting in render queue'
  if (job.status === 'completed') return `Rendered ${job.completed_frames.length} ${job.completed_frames.length === 1 ? 'frame' : 'frames'}`
  if (job.status === 'interrupted') return 'Render interrupted'
  if (job.status === 'canceled') return 'Render canceled'
  return 'Render failed'
}

function emptyPreviewMessage(job: Job) {
  if (job.status === 'running') return 'First frame is rendering'
  if (job.status === 'queued') return 'Waiting in render queue'
  return statusLine(job)
}

export function RenderWorkspace({ job, demo, onCancel, onRetry, onDelete }: RenderWorkspaceProps) {
  const frames = useMemo(() => job?.completed_frames.slice(-5) ?? [], [job?.completed_frames])
  const previewFrame = frames.at(-1)
  const [selected, setSelected] = useState<Set<number>>(() => previewFrame == null ? new Set() : new Set([previewFrame]))
  useEffect(() => setSelected(previewFrame == null ? new Set() : new Set([previewFrame])), [job?.id, previewFrame])
  const previewUrl = demo ? demoRenderUrl : job && previewFrame != null ? api.frameUrl(job.id, previewFrame, true) : null

  if (!job) {
    return <main className="workspace workspace--empty"><div><h1>No render selected</h1><p>Queue a packed .blend file to begin.</p></div></main>
  }

  function toggleFrame(frame: number) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(frame)) next.delete(frame)
      else next.add(frame)
      return next
    })
  }

  const recoverable = ['failed', 'canceled', 'interrupted'].includes(job.status)
  const deletable = ['completed', 'failed', 'canceled', 'interrupted'].includes(job.status)
  const previewIsActive = job.status === 'queued' || job.status === 'running'
  return (
    <main className="workspace">
      <section className="job-heading">
        <h1>{job.filename}</h1>
        <div className="job-meta">
          <span className={`job-meta__state job-meta__state--${job.status}`}><i />{statusLine(job)}</span><b />
          {job.backend !== 'CPU' ? <><span><RefreshCw size={16} />{job.backend === 'OPTIX' ? 'OptiX' : 'CUDA'}</span><b /></> : null}
          <span>{formatDuration(job.elapsed_seconds)} elapsed</span><b />
          <span>{job.eta_seconds != null ? `${formatDuration(job.eta_seconds)} remaining` : 'Estimate pending'}</span>
        </div>
      </section>
      <section className="preview-section">
        <div className={`render-preview${previewUrl ? '' : ' render-preview--empty'}${previewIsActive ? ' render-preview--active' : ''}`}>
          {previewUrl ? <img src={previewUrl} alt={`Latest rendered frame from ${job.filename}`} /> : <div><RefreshCw size={34} /><span>{emptyPreviewMessage(job)}</span></div>}
        </div>
        <div className="progress-row">
          <strong>{Math.round(job.progress)}%</strong>
          <div className="progress-track"><span style={{ width: `${job.progress}%` }} /></div>
          {job.status === 'running' || job.status === 'queued' ? <button className="button button--danger" onClick={() => void onCancel(job)}><Trash2 size={17} /> Cancel render</button> : null}
          {recoverable ? <button className="button button--outline" onClick={() => void onRetry(job)}><RefreshCw size={17} /> Retry render</button> : null}
        </div>
        {job.error ? <div className="job-error"><AlertTriangle size={18} /><span>{job.error}</span></div> : null}
      </section>
      <section className="frames-section">
        <div className="frames-section__header">
          <h2>Rendered frames</h2>
          <div>
            <button className="button button--subtle" disabled={!selected.size} onClick={() => { if (!demo) void api.downloadArchive(job, [...selected]) }}><Download size={17} /> Download selected</button>
            <button className="button button--subtle" disabled={!frames.length} onClick={() => { if (!demo) void api.downloadArchive(job) }}><Download size={17} /> Download all</button>
            {deletable ? <button className="icon-button" onClick={() => void onDelete(job)} aria-label="Delete job"><XCircle size={19} /></button> : null}
          </div>
        </div>
        <div className="frame-strip">
          {frames.map((frame) => (
            <button key={frame} className={`frame-tile${selected.has(frame) || frame === previewFrame ? ' is-selected' : ''}`} onClick={() => toggleFrame(frame)}>
              <img src={demo ? demoRenderUrl : api.frameUrl(job.id, frame, true)} alt="" />
              <span>{String(frame).padStart(4, '0')}</span>
            </button>
          ))}
          {!frames.length ? <div className="frame-strip__empty">Completed frames will appear here.</div> : null}
        </div>
      </section>
    </main>
  )
}
