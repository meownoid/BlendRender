import { Download, ImageOff, LoaderCircle, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { formatDuration } from '../lib/format'
import type { FrameGroup, Job, Scene } from '../types'

interface SceneWorkspaceProps { scene: Scene | null; frames: FrameGroup[]; jobs: Job[]; loading: boolean; onDelete: (scene: Scene) => Promise<void> }

function formatPodName(podId: string): string {
  return podId.length > 16 ? `${podId.slice(0, 16)}...` : podId
}

export function SceneWorkspace({ scene, frames, jobs, loading, onDelete }: SceneWorkspaceProps) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  const allResults = useMemo(() => frames.flatMap((group) => group.results), [frames])
  if (!scene) return <main className="scene-workspace scene-workspace--empty"><ImageOff size={34} /><h1>No scene selected</h1><p>Upload a scene, then create jobs from any connected pod.</p></main>
  const currentScene = scene
  function toggle(resultId: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(resultId)) next.delete(resultId)
      else next.add(resultId)
      return next
    })
  }
  async function downloadArchive() {
    setDownloading(true)
    setDownloadError('')
    try {
      await api.downloadSceneArchive(currentScene, selected.size ? [...selected] : undefined)
    } catch (reason) {
      setDownloadError(reason instanceof Error ? reason.message : 'Unable to download results')
    } finally {
      setDownloading(false)
    }
  }
  const active = jobs.filter((job) => job.status === 'queued' || job.status === 'running')
  return <main className="scene-workspace">
    <section className="scene-heading"><div><h1>{scene.name}</h1><p>{scene.source_kind === 'zip' ? 'Project archive' : 'Blender file'} · {scene.result_count} published results · {active.length} active jobs</p></div><button className="button button--danger" onClick={() => void onDelete(scene)}><Trash2 size={16} /> Delete scene</button></section>
    <section className="scene-results"><header><div><h2>Results by frame</h2><p>Every completed variant is retained.</p></div><div className="results-download"><button className="button button--subtle" disabled={!allResults.length || downloading} onClick={() => void downloadArchive()}>{downloading ? <LoaderCircle className="is-spinning" size={16} /> : <Download size={16} />}{downloading ? 'Preparing download…' : selected.size ? `Download ${selected.size}` : 'Download all'}</button>{downloading ? <div className="results-download__progress" role="status" aria-label="Preparing result archive"><span /></div> : null}{downloadError ? <p className="results-download__error" role="alert">{downloadError}</p> : null}</div></header>
      {loading ? <div className="results-empty results-empty--loading" role="status" aria-live="polite"><LoaderCircle className="is-spinning" size={24} /><span>Loading scene results…</span></div> : frames.map((group) => <section className="frame-group" key={group.frame}><h3>Frame {String(group.frame).padStart(4, '0')}</h3><div className="variant-grid">{group.results.map((result) => <article className={`variant-card${selected.has(result.id) ? ' is-selected' : ''}`} key={result.id} onClick={() => toggle(result.id)}>
        <img src={api.resultImageUrl(scene.id, result.id, true)} alt={`Frame ${result.frame}, ${result.backend} render`} /><footer><div><strong>{result.backend === 'OPTIX' ? 'OptiX' : result.backend}</strong><span>{result.hardware.join(', ')}</span></div><div className="variant-card__controls"><span>{result.samples} samples</span><span>{formatDuration(result.render_seconds)}</span><span title={result.pod_id}>{formatPodName(result.pod_id)}</span><a className="result-download" href={api.resultImageUrl(scene.id, result.id)} aria-label={`Download frame ${result.frame} result`} onClick={(event) => event.stopPropagation()}><Download size={14} /></a></div></footer>
      </article>)}</div></section>)}
      {!loading && !frames.length ? <div className="results-empty">Rendered frames from every pod will appear here.</div> : null}
    </section>
  </main>
}
