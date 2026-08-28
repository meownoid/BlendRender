import type { TelemetrySample } from '../types'

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

function sampleResources(sample: TelemetrySample): ResourceSample {
  return {
    capturedAt: Date.parse(sample.captured_at),
    cpuUtilization: sample.cpu_utilization,
    gpuUtilization: sample.gpu_utilization,
    memoryUtilization: percentage(sample.memory_used_bytes, sample.memory_total_bytes) ?? 0,
    vramUtilization: sample.vram_used_mb != null && sample.vram_total_mb != null
      ? percentage(sample.vram_used_mb, sample.vram_total_mb)
      : null,
    memoryUsedBytes: sample.memory_used_bytes,
    memoryTotalBytes: sample.memory_total_bytes,
    vramUsedMb: sample.vram_used_mb,
    vramTotalMb: sample.vram_total_mb,
  }
}

export function deserializeResourceHistory(samples: TelemetrySample[]): ResourceSample[] {
  return samples.map(sampleResources)
}
