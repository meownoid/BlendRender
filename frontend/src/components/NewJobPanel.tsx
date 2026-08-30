import { Play, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Backend, CreateJobForm, Scene, SystemInfo } from '../types'

interface NewJobPanelProps {
  open: boolean
  scene: Scene | null
  system: SystemInfo | null
  busy: boolean
  onClose: () => void
  onSubmit: (form: CreateJobForm) => Promise<void>
}

export function NewJobPanel({ open, scene, system, busy, onClose, onSubmit }: NewJobPanelProps) {
  const [mode, setMode] = useState<'still' | 'range'>('range')
  const [frame, setFrame] = useState(1)
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(120)
  const [backend, setBackend] = useState<Backend>('OPTIX')
  const [samples, setSamples] = useState('')
  const [resolutionX, setResolutionX] = useState('')
  const [resolutionY, setResolutionY] = useState('')
  const [resolutionPercentage, setResolutionPercentage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const preferred = (['OPTIX', 'CUDA', 'CPU'] as Backend[]).find((item) => system?.available_backends.includes(item))
    if (preferred && !system?.available_backends.includes(backend)) setBackend(preferred)
  }, [backend, system])
  if (!open) return null
  async function submit() {
    if (!scene) return setError('Select a scene first.')
    if (mode === 'range' && start > end) return setError('Start frame must not exceed end frame.')
    if (Boolean(resolutionX) !== Boolean(resolutionY)) return setError('Width and height must be provided together.')
    try {
      setError('')
      await onSubmit({
        scene_id: scene.id,
        mode,
        frame,
        start,
        end,
        backend,
        samples: samples ? Number(samples) : undefined,
        resolution_x: resolutionX ? Number(resolutionX) : undefined,
        resolution_y: resolutionY ? Number(resolutionY) : undefined,
        resolution_percentage: resolutionPercentage ? Number(resolutionPercentage) : undefined,
      })
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to create job') }
  }
  return <aside className="side-panel" aria-label="New render job">
    <header><h2>New render</h2><button className="icon-button" onClick={onClose}><X /></button></header>
    <label className="field">Scene<input readOnly value={scene?.name ?? 'No scene selected'} /></label>
    <fieldset><legend>Render type</legend><div className="segmented"><button className={mode === 'still' ? 'is-selected' : ''} onClick={() => setMode('still')}>Still</button><button className={mode === 'range' ? 'is-selected' : ''} onClick={() => setMode('range')}>Range</button></div></fieldset>
    {mode === 'still' ? <label className="field"><span>Frame</span><input type="number" value={frame} onChange={(event) => setFrame(Number(event.target.value))} /></label> : <div className="range-fields"><label className="field"><span>Start</span><input type="number" value={start} onChange={(event) => setStart(Number(event.target.value))} /></label><label className="field"><span>End</span><input type="number" value={end} onChange={(event) => setEnd(Number(event.target.value))} /></label></div>}
    <fieldset><legend>Backend on this pod</legend><div className="segmented segmented--three">{(['OPTIX', 'CUDA', 'CPU'] as Backend[]).map((item) => <button key={item} disabled={!system?.available_backends.includes(item)} className={backend === item ? 'is-selected' : ''} onClick={() => setBackend(item)}>{item === 'OPTIX' ? 'OptiX' : item}</button>)}</div></fieldset>
    <label className="field"><span>Samples (optional)</span><input type="number" min="1" value={samples} placeholder="Use scene setting" onChange={(event) => setSamples(event.target.value)} /></label>
    <div className="range-fields"><label className="field"><span>Width (optional)</span><input type="number" min="4" value={resolutionX} placeholder="Scene width" onChange={(event) => setResolutionX(event.target.value)} /></label><label className="field"><span>Height (optional)</span><input type="number" min="4" value={resolutionY} placeholder="Scene height" onChange={(event) => setResolutionY(event.target.value)} /></label></div>
    <label className="field"><span>Resolution scale (optional)</span><input type="number" min="1" max="100" value={resolutionPercentage} placeholder="Scene percentage" onChange={(event) => setResolutionPercentage(event.target.value)} /></label>
    {error ? <p className="panel-error">{error}</p> : null}
    <button className="button button--primary panel-submit" onClick={() => void submit()} disabled={busy || !scene}><Play size={18} /> {busy ? 'Creating…' : 'Create job'}</button>
  </aside>
}
