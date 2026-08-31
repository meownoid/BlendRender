import { Box, FileStack, Plus } from 'lucide-react'
import { formatBytes } from '../lib/format'
import type { Scene } from '../types'

interface SceneRailProps {
  scenes: Scene[]
  selectedId: string | null
  onSelect: (id: string) => void
  onUpload: () => void
}

export function SceneRail({ scenes, selectedId, onSelect, onUpload }: SceneRailProps) {
  return (
    <aside className="scene-rail">
      <div className="rail-heading"><div><span>Scenes</span><strong>{scenes.length}</strong></div><button className="icon-button" onClick={onUpload} aria-label="Upload scene"><Plus size={19} /></button></div>
      <div className="scene-list">
        {scenes.map((scene) => <button key={scene.id} className={`scene-row${scene.id === selectedId ? ' is-selected' : ''}`} onClick={() => onSelect(scene.id)}>
          <Box size={18} /><span><strong>{scene.name}</strong><small>{formatBytes(scene.size_bytes)} · {scene.result_count} results · {scene.job_count} jobs</small></span>
        </button>)}
        {!scenes.length ? <div className="rail-empty"><FileStack size={26} />Upload a .blend or project ZIP to begin.</div> : null}
      </div>
    </aside>
  )
}
