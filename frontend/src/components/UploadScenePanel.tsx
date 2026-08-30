import { FileUp, X } from 'lucide-react'
import { type DragEvent, useRef, useState } from 'react'
import { formatBytes } from '../lib/format'
import type { UploadProgress } from '../types'

interface UploadScenePanelProps {
  open: boolean
  busy: boolean
  progress: UploadProgress | null
  onClose: () => void
  onUpload: (file: File, name: string) => Promise<void>
}

export function UploadScenePanel({ open, busy, progress, onClose, onUpload }: UploadScenePanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  if (!open) return null
  async function submit() {
    if (!file) return setError('Choose a .blend file or a project ZIP archive.')
    setError('')
    try { await onUpload(file, name); setFile(null); setName('') } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to upload scene') }
  }
  function choose(candidate?: File) {
    if (!candidate) return
    if (!/\.(blend|zip)$/i.test(candidate.name)) return setError('Choose a .blend file or a project ZIP archive.')
    setError(''); setFile(candidate)
  }
  function dragOver(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
    setDragging(true)
  }
  function dragLeave(event: DragEvent<HTMLButtonElement>) {
    const nextTarget = event.relatedTarget
    if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) setDragging(false)
  }
  function drop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault()
    setDragging(false)
    choose(event.dataTransfer.files[0])
  }
  const percent = progress?.total ? Math.min(100, Math.round((progress.loaded / progress.total) * 100)) : null
  return <aside className="side-panel" aria-label="Upload scene">
    <header><h2>Upload scene</h2><button className="icon-button" onClick={onClose} disabled={busy}><X /></button></header>
    <button
      className={`dropzone${file ? ' has-file' : ''}${dragging ? ' is-dragging' : ''}`}
      onClick={() => inputRef.current?.click()}
      onDragOver={dragOver}
      onDragLeave={dragLeave}
      onDrop={drop}
      disabled={busy}
    >
      <FileUp size={36} />
      <strong>{dragging ? 'Drop file here' : (file?.name ?? 'Choose a .blend or project ZIP')}</strong>
      <span>{file ? formatBytes(file.size) : 'ZIPs need one .blend and relative resources.'}</span>
    </button>
    <input className="visually-hidden" ref={inputRef} type="file" accept=".blend,.zip" onChange={(event) => choose(event.target.files?.[0])} />
    <label className="field"><span>Name (optional)</span><input value={name} maxLength={200} placeholder={file?.name ?? 'Uses the uploaded file name'} onChange={(event) => setName(event.target.value)} disabled={busy} /></label>
    {busy ? <div className="upload-progress"><strong>{percent == null ? 'Uploading…' : `Uploading ${percent}%`}</strong><div className="progress-track"><span style={{ width: `${percent ?? 35}%` }} /></div></div> : null}
    {error ? <p className="panel-error">{error}</p> : null}
    <button className="button button--primary panel-submit" onClick={() => void submit()} disabled={busy || !file}>Create scene</button>
  </aside>
}
