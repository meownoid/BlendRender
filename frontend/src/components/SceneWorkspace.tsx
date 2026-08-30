import { Download, ImageOff, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { formatDuration } from '../lib/format'
import type { FrameGroup, Job, Scene } from '../types'

interface SceneWorkspaceProps { scene: Scene | null; frames: FrameGroup[]; jobs: Job[]; onDelete: (scene: Scene) => Promise<void> }

export function SceneWorkspace({ scene, frames, jobs, onDelete }: SceneWorkspaceProps) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const allResults = useMemo(() => frames.flatMap((group) => group.results), [frames])
  if (!scene) return <main className="scene-workspace scene-workspace--empty"><ImageOff size={34} /><h1>No scene selected</h1><p>Upload a scene, then create jobs from any connected pod.</p></main>
  function toggle(resultId: string) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(resultId)) next.delete(resultId)
      else next.add(resultId)
      return next
    })
  }
  const active = jobs.filter((job) => job.status === 'queued' || job.status === 'running')
  return <main className="scene-workspace">
    <section className="scene-heading"><div><h1>{scene.name}</h1><p>{scene.source_kind === 'zip' ? 'Project archive' : 'Blend file'} · {scene.result_count} published results · {active.length} active jobs</p></div><button className="button button--danger" onClick={() => void onDelete(scene)}><Trash2 size={16} /> Delete scene</button></section>
    <section className="scene-results"><header><div><h2>Results by frame</h2><p>Every completed variant is retained.</p></div><button className="button button--subtle" disabled={!allResults.length} onClick={() => void api.downloadSceneArchive(scene, selected.size ? [...selected] : undefined)}><Download size={16} /> {selected.size ? `Download ${selected.size}` : 'Download all'}</button></header>
      {frames.map((group) => <section className="frame-group" key={group.frame}><h3>Frame {String(group.frame).padStart(4, '0')}</h3><div className="variant-grid">{group.results.map((result) => <article className={`variant-card${selected.has(result.id) ? ' is-selected' : ''}`} key={result.id} onClick={() => toggle(result.id)}>
        <img src={api.resultImageUrl(scene.id, result.id, true)} alt={`Frame ${result.frame}, ${result.backend} render`} /><footer><div><strong>{result.backend === 'OPTIX' ? 'OptiX' : result.backend}</strong><span>{result.hardware.join(', ')}</span></div><div><span>{result.samples} samples</span><span>{formatDuration(result.render_seconds)}</span><span>{result.pod_id}</span><a className="result-download" href={api.resultImageUrl(scene.id, result.id)} aria-label={`Download frame ${result.frame} result`} onClick={(event) => event.stopPropagation()}><Download size={14} /></a></div></footer>
      </article>)}</div></section>)}
      {!frames.length ? <div className="results-empty">Rendered frames from every pod will appear here.</div> : null}
    </section>
  </main>
}
