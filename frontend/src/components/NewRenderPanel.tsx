import { FileUp, Play, X } from 'lucide-react'
import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from 'react'
import { formatBytes } from '../lib/format'
import type { RenderForm, SystemInfo, VisibleBackend } from '../types'

interface NewRenderPanelProps {
  open: boolean
  system: SystemInfo | null
  busy: boolean
  onClose: () => void
  onSubmit: (form: RenderForm) => Promise<void>
}

export function NewRenderPanel({ open, system, busy, onClose, onSubmit }: NewRenderPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<'still' | 'range'>('range')
  const [frame, setFrame] = useState(1)
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(120)
  const [backend, setBackend] = useState<VisibleBackend>('OPTIX')
  const [error, setError] = useState('')

  function acceptFile(candidate?: File) {
    if (!candidate) return
    if (!candidate.name.toLowerCase().endsWith('.blend')) {
      setError('Choose a .blend file with packed assets.')
      return
    }
    setFile(candidate)
    setError('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) {
      setError('Choose a packed .blend file first.')
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
    <aside id="new-render-panel" className={`render-panel${open ? ' is-open' : ''}`} aria-hidden={!open}>
      <div className="render-panel__header"><h2>New render</h2><button className="icon-button" onClick={onClose} aria-label="Close new render panel"><X size={22} /></button></div>
      <form onSubmit={submit}>
        <button className={`dropzone${file ? ' has-file' : ''}`} type="button" onClick={() => inputRef.current?.click()} onDrop={drop} onDragOver={(event) => event.preventDefault()}>
          <FileUp size={56} strokeWidth={1.4} />
          {file ? <><strong>{file.name}</strong><span>{formatBytes(file.size)}</span></> : <><span>Drop a packed .blend file</span><span>or <em>choose a file</em></span></>}
        </button>
        <input ref={inputRef} className="visually-hidden" type="file" accept=".blend" onChange={(event: ChangeEvent<HTMLInputElement>) => acceptFile(event.target.files?.[0])} />
        <fieldset><legend>Mode</legend><div className="segmented"><button type="button" className={mode === 'still' ? 'is-selected' : ''} onClick={() => setMode('still')}>Still</button><button type="button" className={mode === 'range' ? 'is-selected' : ''} onClick={() => setMode('range')}>Frame range</button></div></fieldset>
        {mode === 'still' ? <label className="field">Frame<input type="number" value={frame} onChange={(event) => setFrame(Number(event.target.value))} /></label> : <div className="range-fields"><label className="field">Start<input type="number" value={start} onChange={(event) => setStart(Number(event.target.value))} /></label><label className="field">End<input type="number" value={end} onChange={(event) => setEnd(Number(event.target.value))} /></label></div>}
        <fieldset><legend>Backend</legend><div className="segmented">{(['OPTIX', 'CUDA'] as VisibleBackend[]).map((value) => <button key={value} type="button" disabled={!system?.available_backends.includes(value)} className={backend === value ? 'is-selected' : ''} onClick={() => setBackend(value)}>{value === 'OPTIX' ? 'OptiX' : 'CUDA'}</button>)}</div></fieldset>
        <div className="render-panel__error" role="alert">{error}</div>
        <button className="button button--primary render-panel__submit" disabled={busy || !file || !system?.available_backends.includes(backend)}><Play size={20} /> {busy ? 'Queueing…' : 'Queue render'}</button>
      </form>
    </aside>
  )
}
