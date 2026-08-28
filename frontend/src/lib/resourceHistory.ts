import type { SystemInfo } from '../types'

export const RESOURCE_HISTORY_MS = 15 * 60 * 1000

export interface ResourceSample {
  capturedAt: number
  cpuUtilization: number
  gpuUtilization: number | null
  memoryUtilization: number
  vramUtilization: number | null
  memoryUsedBytes: number
  memoryTotalBytes: number
  vramUsedMb: number | null
  vramTotalMb: number | null
}

function percentage(used: number, total: number): number | null {
  if (total <= 0) return null
  return Math.max(0, Math.min(100, used / total * 100))
}

export function sampleResources(system: SystemInfo, capturedAt = Date.now()): ResourceSample {
  const gpuUtilization = system.gpus.length
    ? Math.max(...system.gpus.map((gpu) => gpu.utilization))
    : null
  const vramUsedMb = system.gpus.length
    ? system.gpus.reduce((total, gpu) => total + gpu.memory_used_mb, 0)
    : null
  const vramTotalMb = system.gpus.length
    ? system.gpus.reduce((total, gpu) => total + gpu.memory_total_mb, 0)
    : null

  return {
    capturedAt,
    cpuUtilization: system.cpu_utilization,
    gpuUtilization,
    memoryUtilization: percentage(system.memory_used_bytes, system.memory_total_bytes) ?? 0,
    vramUtilization: vramUsedMb != null && vramTotalMb != null
      ? percentage(vramUsedMb, vramTotalMb)
      : null,
    memoryUsedBytes: system.memory_used_bytes,
    memoryTotalBytes: system.memory_total_bytes,
    vramUsedMb,
    vramTotalMb,
  }
}

export function appendResourceSample(
  history: ResourceSample[],
  system: SystemInfo,
  capturedAt = Date.now(),
): ResourceSample[] {
  const cutoff = capturedAt - RESOURCE_HISTORY_MS
  return [...history, sampleResources(system, capturedAt)].filter((sample) => sample.capturedAt >= cutoff)
}
