import { Activity, X } from 'lucide-react'
import { formatBytes } from '../lib/format'
import type { ResourceSample } from '../lib/resourceHistory'
import type { SystemInfo } from '../types'

interface SystemPanelProps {
  open: boolean
  system: SystemInfo | null
  samples: ResourceSample[]
  onClose: () => void
}

interface ResourcePlotProps {
  label: string
  color: string
  samples: ResourceSample[]
  value: (sample: ResourceSample) => number | null
  detail: (sample: ResourceSample) => string
}

function formatPercent(value: number | null): string {
  return value == null ? 'Unavailable' : `${Math.round(value)}%`
}

function ResourcePlot({ label, color, samples, value, detail }: ResourcePlotProps) {
  const current = samples.length ? samples[samples.length - 1] : null
  const currentValue = current ? value(current) : null
  const chartWidth = 300
  const chartHeight = 92
  const chartPadding = 8
  const newestAt = current?.capturedAt ?? Date.now()
  const oldestAt = newestAt - 15 * 60 * 1000
  const points = samples.flatMap((sample) => {
    const sampleValue = value(sample)
    if (sampleValue == null) return []
    const x = chartPadding + (sample.capturedAt - oldestAt) / (newestAt - oldestAt) * (chartWidth - chartPadding * 2)
    const y = chartPadding + (100 - sampleValue) / 100 * (chartHeight - chartPadding * 2)
    return [`${x.toFixed(1)},${y.toFixed(1)}`]
  })

  return (
    <section className="resource-plot" aria-labelledby={`resource-plot-${label}`}>
      <div className="resource-plot__header">
        <div><h3 id={`resource-plot-${label}`}>{label}</h3><span>{current ? detail(current) : 'Waiting for telemetry'}</span></div>
        <strong>{formatPercent(currentValue)}</strong>
      </div>
      {currentValue == null ? <div className="resource-plot__empty">Unavailable on this node</div> : (
        <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`${label} utilization ${formatPercent(currentValue)} over the last 15 minutes`}>
          {[25, 50, 75].map((line) => <line key={line} x1={chartPadding} x2={chartWidth - chartPadding} y1={chartPadding + (100 - line) / 100 * (chartHeight - chartPadding * 2)} y2={chartPadding + (100 - line) / 100 * (chartHeight - chartPadding * 2)} />)}
          {points.length > 1 ? <polyline points={points.join(' ')} style={{ stroke: color }} /> : <circle cx={chartWidth - chartPadding} cy={chartPadding + (100 - (currentValue ?? 0)) / 100 * (chartHeight - chartPadding * 2)} r="3" style={{ fill: color }} />}
          <text x={chartPadding} y={chartHeight - 1}>15m</text><text x={chartWidth - chartPadding} y={chartHeight - 1} textAnchor="end">now</text>
        </svg>
      )}
    </section>
  )
}

export function SystemPanel({ open, system, samples, onClose }: SystemPanelProps) {
  const latest = samples.length ? samples[samples.length - 1] : null
  return (
    <aside id="system-panel" className={`side-panel system-panel${open ? ' is-open' : ''}`} hidden={!open} aria-hidden={!open} aria-labelledby="system-panel-title">
      <div className="render-panel__header"><div><h2 id="system-panel-title">Performance</h2><p>Current Pod · Last 15 minutes</p></div><button className="icon-button" onClick={onClose} aria-label="Close performance panel"><X size={22} /></button></div>
      {!system || !latest ? <div className="system-panel__loading"><Activity size={24} /> Waiting for system telemetry</div> : <div className="system-panel__plots">
        <ResourcePlot label="CPU" color="var(--accent)" samples={samples} value={(sample) => sample.cpuUtilization} detail={() => 'Host utilization'} />
        <ResourcePlot label="MEM" color="var(--blue)" samples={samples} value={(sample) => sample.memoryUtilization} detail={(sample) => `${formatBytes(sample.memoryUsedBytes)} of ${formatBytes(sample.memoryTotalBytes)}`} />
        <ResourcePlot label="GPU" color="var(--green)" samples={samples} value={(sample) => sample.gpuUtilization} detail={() => system.gpus.length ? `${system.gpus.length} GPU${system.gpus.length === 1 ? '' : 's'} · peak utilization` : 'No NVIDIA GPU detected'} />
        <ResourcePlot label="VRAM" color="#bd8cff" samples={samples} value={(sample) => sample.vramUtilization} detail={(sample) => sample.vramUsedMb == null || sample.vramTotalMb == null ? 'No NVIDIA GPU detected' : `${sample.vramUsedMb.toLocaleString()} MB of ${sample.vramTotalMb.toLocaleString()} MB`} />
      </div>}
    </aside>
  )
}
