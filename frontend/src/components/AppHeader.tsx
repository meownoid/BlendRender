import { Activity, LogOut, Plus } from 'lucide-react'
import { formatBytes } from '../lib/format'
import type { ResourceSample } from '../lib/resourceHistory'
import type { SystemInfo } from '../types'
import { Brand } from './Brand'

interface AppHeaderProps {
  system: SystemInfo | null
  latestSample: ResourceSample | null
  renderPanelOpen: boolean
  systemPanelOpen: boolean
  onOpenPanel: () => void
  onOpenSystem: () => void
  onLogout: () => void
}

function formatPercent(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value)}%`
}

function formatMegabytes(value: number | null | undefined): string {
  return value == null ? '—' : formatBytes(value * 1024 ** 2)
}

export function AppHeader({ system, latestSample, renderPanelOpen, systemPanelOpen, onOpenPanel, onOpenSystem, onLogout }: AppHeaderProps) {
  const summary = latestSample
    ? `CPU ${formatPercent(latestSample.cpuUtilization)}, GPU ${formatPercent(latestSample.gpuUtilization)}, memory ${formatBytes(latestSample.memoryUsedBytes)} of ${formatBytes(latestSample.memoryTotalBytes)}, VRAM ${formatMegabytes(latestSample.vramUsedMb)} of ${formatMegabytes(latestSample.vramTotalMb)}`
    : 'System telemetry unavailable'
  return (
    <header className="app-header">
      <Brand />
      <div className="app-header__actions">
        <button className={`button button--outline${renderPanelOpen ? ' is-active' : ''}`} onClick={onOpenPanel} aria-controls="new-render-panel" aria-expanded={renderPanelOpen}>
          <Plus size={19} /> New render
        </button>
        <button className={`system-meter${systemPanelOpen ? ' is-active' : ''}`} onClick={onOpenSystem} aria-controls="system-panel" aria-expanded={systemPanelOpen} aria-label={`Open system stats. ${summary}`} title={summary}>
          <Activity className="system-meter__icon" size={18} />
          <span className="system-meter__metric"><b>CPU</b><strong>{formatPercent(latestSample?.cpuUtilization)}</strong></span>
          <span className="system-meter__metric"><b>GPU</b><strong>{formatPercent(latestSample?.gpuUtilization)}</strong></span>
          <span className="system-meter__metric"><b>MEM</b><strong>{latestSample ? formatPercent(latestSample.memoryUtilization) : '—'}</strong></span>
          <span className="system-meter__metric system-meter__metric--vram"><b>VRAM</b><strong>{formatPercent(latestSample?.vramUtilization)}</strong></span>
          {!system ? <span className="visually-hidden">System telemetry unavailable</span> : null}
        </button>
        <button className="icon-button app-header__logout" onClick={onLogout} aria-label="Sign out"><LogOut size={20} /></button>
      </div>
    </header>
  )
}
