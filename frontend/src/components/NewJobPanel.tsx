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
  const [mode, setMode] = useState<'still' | 'range'>('still')
  const [frame, setFrame] = useState('1')
  const [start, setStart] = useState('1')
  const [end, setEnd] = useState('120')
  const [backend, setBackend] = useState<Backend>('OPTIX')
  const [samples, setSamples] = useState('')
  const [tileSize, setTileSize] = useState('')
  const [resolutionX, setResolutionX] = useState('')
  const [resolutionY, setResolutionY] = useState('')
  const [resolutionPercentage, setResolutionPercentage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const preferred = (['OPTIX', 'CUDA', 'CPU'] as Backend[]).find((item) => system?.available_backends.includes(item))
    if (preferred && !system?.available_backends.includes(backend)) setBackend(preferred)
  }, [backend, system])
  if (!open) return null

  function parseFrame(value: string): number | null {
    const parsed = Number(value)
    return value && Number.isInteger(parsed) ? parsed : null
  }

  function validateFrameOnBlur(value: string, label: string) {
    setError(parseFrame(value) === null ? `${label} must be an integer.` : '')
  }

  function validateOptionalInteger(value: string, label: string, min: number, max: number): string | null {
    if (!value) return null
    const parsed = Number(value)
    if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
      return `${label} must be a whole number between ${min.toLocaleString()} and ${max.toLocaleString()}.`
    }
    return null
  }

  async function submit() {
    if (!scene) return setError('Select a scene first.')
    const parsedFrame = parseFrame(frame)
    const parsedStart = parseFrame(start)
    const parsedEnd = parseFrame(end)
    if (parsedFrame === null || parsedStart === null || parsedEnd === null) {
      setError('Frame values must be integers.')
      return
    }
    if (mode === 'range' && parsedStart > parsedEnd) return setError('Start frame must not exceed end frame.')
    if (Boolean(resolutionX) !== Boolean(resolutionY)) return setError('Width and height must be provided together.')
    const optionalFieldError = [
      validateOptionalInteger(samples, 'Samples', 1, 1_000_000),
      validateOptionalInteger(tileSize, 'Tile size', 8, 8_192),
      validateOptionalInteger(resolutionX, 'Width', 4, 65_536),
      validateOptionalInteger(resolutionY, 'Height', 4, 65_536),
      validateOptionalInteger(resolutionPercentage, 'Resolution scale', 1, 100),
    ].find((message) => message != null)
    if (optionalFieldError) return setError(optionalFieldError)
    try {
      setError('')
      await onSubmit({
        scene_id: scene.id,
        mode,
        frame: parsedFrame,
        start: parsedStart,
        end: parsedEnd,
        backend,
        samples: samples ? Number(samples) : undefined,
        tile_size: tileSize ? Number(tileSize) : undefined,
        resolution_x: resolutionX ? Number(resolutionX) : undefined,
        resolution_y: resolutionY ? Number(resolutionY) : undefined,
        resolution_percentage: resolutionPercentage ? Number(resolutionPercentage) : undefined,
      })
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to create job') }
  }
  return <aside className="side-panel" aria-label="New render job">
    <header><h2>New render</h2><button className="icon-button" onClick={onClose}><X /></button></header>
    <label className="field">Scene<input data-1p-ignore="true" readOnly value={scene?.name ?? 'No scene selected'} /></label>
    <fieldset><legend>Render type</legend><div className="segmented"><button className={mode === 'still' ? 'is-selected' : ''} onClick={() => setMode('still')}>Still</button><button className={mode === 'range' ? 'is-selected' : ''} onClick={() => setMode('range')}>Range</button></div></fieldset>
    {mode === 'still' ? <label className="field"><span>Frame</span><input data-1p-ignore="true" type="number" value={frame} onChange={(event) => setFrame(event.target.value)} onBlur={(event) => validateFrameOnBlur(event.target.value, 'Frame')} /></label> : <div className="range-fields"><label className="field"><span>Start</span><input data-1p-ignore="true" type="number" value={start} onChange={(event) => setStart(event.target.value)} onBlur={(event) => validateFrameOnBlur(event.target.value, 'Start frame')} /></label><label className="field"><span>End</span><input data-1p-ignore="true" type="number" value={end} onChange={(event) => setEnd(event.target.value)} onBlur={(event) => validateFrameOnBlur(event.target.value, 'End frame')} /></label></div>}
    <fieldset><legend>Backend on this pod</legend><div className="segmented segmented--three">{(['OPTIX', 'CUDA', 'CPU'] as Backend[]).map((item) => <button key={item} disabled={!system?.available_backends.includes(item)} className={backend === item ? 'is-selected' : ''} onClick={() => setBackend(item)}>{item === 'OPTIX' ? 'OptiX' : item}</button>)}</div></fieldset>
    <label className="field"><span>Samples (optional)</span><input data-1p-ignore="true" type="number" min="1" value={samples} placeholder="Use scene setting" onChange={(event) => setSamples(event.target.value)} /></label>
    <label className="field"><span>Tile size (optional)</span><input data-1p-ignore="true" type="number" min="8" max="8192" value={tileSize} placeholder="Use scene setting" onChange={(event) => setTileSize(event.target.value)} /></label>
    <div className="range-fields"><label className="field"><span>Width (optional)</span><input data-1p-ignore="true" type="number" min="4" value={resolutionX} placeholder="Scene width" onChange={(event) => setResolutionX(event.target.value)} /></label><label className="field"><span>Height (optional)</span><input data-1p-ignore="true" type="number" min="4" value={resolutionY} placeholder="Scene height" onChange={(event) => setResolutionY(event.target.value)} /></label></div>
    <label className="field"><span>Resolution scale (optional)</span><input data-1p-ignore="true" type="number" min="1" max="100" value={resolutionPercentage} placeholder="Scene percentage" onChange={(event) => setResolutionPercentage(event.target.value)} /></label>
    {error ? <p className="panel-error">{error}</p> : null}
    <button className="button button--primary panel-submit" onClick={() => void submit()} disabled={busy || !scene}><Play size={18} /> {busy ? 'Creating…' : 'Create job'}</button>
  </aside>
}
