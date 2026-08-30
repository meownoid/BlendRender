import { FileUp, Play, X } from 'lucide-react'
import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from 'react'
import { formatBytes } from '../lib/format'
import type { Backend, RenderForm, SystemInfo, UploadProgress } from '../types'

interface NewRenderPanelProps {
  open: boolean
  system: SystemInfo | null
  busy: boolean
  uploadProgress: UploadProgress | null
  onClose: () => void
  onSubmit: (form: RenderForm) => Promise<void>
}

export function NewRenderPanel({ open, system, busy, uploadProgress, onClose, onSubmit }: NewRenderPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<'still' | 'range'>('range')
  const [frame, setFrame] = useState(1)
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(120)
  const [backend, setBackend] = useState<Backend>('OPTIX')
  const [error, setError] = useState('')

  const preferredBackend = (['OPTIX', 'CUDA', 'CPU'] as Backend[]).find((value) => system?.available_backends.includes(value))
  const uploadTotal = uploadProgress?.total
  const uploadLoaded = uploadProgress?.loaded ?? 0
  const uploadPercent = uploadTotal == null || uploadTotal <= 0
    ? null
    : Math.min(100, Math.round(uploadLoaded / uploadTotal * 100))
  const uploadStatus = uploadPercent == null
    ? 'Uploading…'
    : uploadPercent === 100 ? 'Finalizing upload…' : `Uploading ${uploadPercent}%`
  const uploadDetail = uploadTotal == null || uploadTotal <= 0
    ? `${formatBytes(uploadLoaded)} uploaded`
    : `${formatBytes(uploadLoaded)} / ${formatBytes(uploadTotal)}`

  useEffect(() => {
    if (preferredBackend && !system?.available_backends.includes(backend)) setBackend(preferredBackend)
  }, [backend, preferredBackend, system])

  function acceptFile(candidate?: File) {
    if (!candidate) return
    if (!/\.(blend|zip)$/i.test(candidate.name)) {
      setError('Choose a .blend file or a project .zip archive.')
      return
    }
    setFile(candidate)
    setError('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) {
      setError('Choose a .blend file or a project .zip archive first.')
      return
    }
    if (mode === 'range' && start > end) {
      setError('Start frame must not exceed end frame.')
      return
    }
    setError('')
    try {
      await onSubmit({ file, mode, frame, start, end, backend })
      setFile(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to queue render')
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    acceptFile(event.dataTransfer.files[0])
  }

  return (
    <aside id="new-render-panel" className={`render-panel${open ? ' is-open' : ''}`} hidden={!open} aria-hidden={!open}>
      <div className="render-panel__header"><h2>New render</h2><button className="icon-button" onClick={onClose} aria-label="Close new render panel" disabled={busy}><X size={22} /></button></div>
      <form onSubmit={submit} data-1p-ignore="true">
        <button className={`dropzone${file ? ' has-file' : ''}`} type="button" disabled={busy} onClick={() => inputRef.current?.click()} onDrop={drop} onDragOver={(event) => event.preventDefault()}>
          <FileUp size={56} strokeWidth={1.4} />
          {file ? <><strong>{file.name}</strong><span>{formatBytes(file.size)}</span></> : <><span>Drop a .blend file or project .zip</span><span>ZIPs must contain one .blend and relative resources</span></>}
        </button>
        <input ref={inputRef} className="visually-hidden" type="file" accept=".blend,.zip" disabled={busy} onChange={(event: ChangeEvent<HTMLInputElement>) => acceptFile(event.target.files?.[0])} />
        <fieldset><legend>Mode</legend><div className="segmented"><button type="button" disabled={busy} className={mode === 'still' ? 'is-selected' : ''} onClick={() => setMode('still')}>Still</button><button type="button" disabled={busy} className={mode === 'range' ? 'is-selected' : ''} onClick={() => setMode('range')}>Frame range</button></div></fieldset>
        {mode === 'still' ? <label className="field field--single">Frame<input type="number" disabled={busy} value={frame} onChange={(event) => setFrame(Number(event.target.value))} /></label> : <div className="range-fields"><label className="field">Start<input type="number" disabled={busy} value={start} onChange={(event) => setStart(Number(event.target.value))} /></label><label className="field">End<input type="number" disabled={busy} value={end} onChange={(event) => setEnd(Number(event.target.value))} /></label></div>}
        <fieldset><legend>Backend</legend><div className="segmented segmented--three">{(['OPTIX', 'CUDA', 'CPU'] as Backend[]).map((value) => <button key={value} type="button" disabled={busy || !system?.available_backends.includes(value)} className={backend === value ? 'is-selected' : ''} onClick={() => setBackend(value)}>{value === 'OPTIX' ? 'OptiX' : value}</button>)}</div></fieldset>
        {busy ? <div className={`upload-progress${uploadPercent == null ? ' upload-progress--indeterminate' : ''}`} role="status" aria-live="polite">
          <div className="upload-progress__labels"><strong>{uploadStatus}</strong><span>{uploadDetail}</span></div>
          <div className="upload-progress__track" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={uploadPercent ?? undefined} aria-valuetext={uploadStatus}>
            <span style={uploadPercent == null ? undefined : { width: `${uploadPercent}%` }} />
          </div>
        </div> : null}
        <div className="render-panel__error" role="alert">{error}</div>
        <button className="button button--primary render-panel__submit" disabled={busy || !file || !system?.available_backends.includes(backend)}><Play size={20} /> {busy ? 'Uploading…' : 'Queue render'}</button>
      </form>
    </aside>
  )
}
