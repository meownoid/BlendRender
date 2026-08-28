import { LogOut, Plus } from 'lucide-react'
import type { SystemInfo } from '../types'
import { Brand } from './Brand'

interface AppHeaderProps {
  system: SystemInfo | null
  panelOpen: boolean
  onOpenPanel: () => void
  onLogout: () => void
}

export function AppHeader({ system, panelOpen, onOpenPanel, onLogout }: AppHeaderProps) {
  const gpu = system?.gpus[0]
  const points = [18, 16, 19, 12, 15, 9, 17, 11, 14, 8, 12, 10, 15, 9, 16, 11]
  return (
    <header className="app-header">
      <Brand />
      <div className="app-header__actions">
        <button className={`button button--outline${panelOpen ? ' is-active' : ''}`} onClick={onOpenPanel} aria-controls="new-render-panel" aria-expanded={panelOpen}>
          <Plus size={19} /> New render
        </button>
        <div className="gpu-meter" title={gpu ? `${gpu.utilization}% GPU · ${gpu.memory_used_mb} MB used` : 'No GPU detected'}>
          <span>{gpu?.name ?? 'GPU unavailable'}</span>
          <svg viewBox="0 0 72 24" role="img" aria-label={`${gpu?.utilization ?? 0}% GPU utilization`}>
            <polyline points={points.map((y, index) => `${index * 4.7},${y}`).join(' ')} />
          </svg>
        </div>
        <button className="icon-button app-header__logout" onClick={onLogout} aria-label="Sign out"><LogOut size={20} /></button>
      </div>
    </header>
  )
}
