export function formatDuration(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const rounded = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(rounded / 60)
  const remaining = rounded % 60
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
  return `${minutes}m ${String(remaining).padStart(2, '0')}s`
}

export function frameLabel(job: { mode: 'still' | 'range'; frame_start: number; frame_end: number }): string {
  return job.mode === 'still' ? `Frame ${job.frame_start}` : `Frames ${job.frame_start}–${job.frame_end}`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 ** 3) return `${Math.round(bytes / 1024 ** 2)} MB`
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

