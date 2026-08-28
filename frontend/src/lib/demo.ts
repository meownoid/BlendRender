import demoRender from '../assets/demo-render.png'
import type { ResourceSample } from './resourceHistory'
import type { Job, SystemInfo } from '../types'

const now = new Date().toISOString()

export const demoJobs: Job[] = [
  {
    id: '00000000-0000-4000-8000-000000000001',
    filename: 'studio_scene.blend',
    status: 'running',
    mode: 'range',
    frame_start: 1,
    frame_end: 120,
    backend: 'OPTIX',
    samples: null,
    resolution_x: null,
    resolution_y: null,
    resolution_percentage: null,
    progress: 46,
    current_frame: 56,
    completed_frames: [52, 53, 54, 55, 56],
    error: null,
    log_tail: '',
    created_at: now,
    started_at: now,
    finished_at: null,
    elapsed_seconds: 728,
    eta_seconds: 840,
    cancel_requested: false,
  },
  {
    id: '00000000-0000-4000-8000-000000000002',
    filename: 'product_turntable.blend',
    status: 'queued',
    mode: 'range',
    frame_start: 1,
    frame_end: 60,
    backend: 'CUDA',
    samples: null,
    resolution_x: null,
    resolution_y: null,
    resolution_percentage: null,
    progress: 0,
    current_frame: null,
    completed_frames: [],
    error: null,
    log_tail: '',
    created_at: now,
    started_at: null,
    finished_at: null,
    elapsed_seconds: 0,
    eta_seconds: null,
    cancel_requested: false,
  },
  {
    id: '00000000-0000-4000-8000-000000000003',
    filename: 'hero_still.blend',
    status: 'completed',
    mode: 'still',
    frame_start: 24,
    frame_end: 24,
    backend: 'OPTIX',
    samples: null,
    resolution_x: null,
    resolution_y: null,
    resolution_percentage: null,
    progress: 100,
    current_frame: null,
    completed_frames: [24],
    error: null,
    log_tail: '',
    created_at: now,
    started_at: now,
    finished_at: now,
    elapsed_seconds: 93,
    eta_seconds: 0,
    cancel_requested: false,
  },
]

export const demoSystem: SystemInfo = {
  blender_version: '5.2.1',
  gpus: [{ name: 'RTX 4090', utilization: 78, memory_used_mb: 11842, memory_total_mb: 24564 }],
  available_backends: ['OPTIX', 'CUDA', 'CPU'],
  cpu_utilization: 34,
  memory_used_bytes: 27 * 1024 ** 3,
  memory_total_bytes: 64 * 1024 ** 3,
  disk_free_bytes: 68 * 1024 ** 3,
  disk_total_bytes: 100 * 1024 ** 3,
}

const demoNow = Date.now()

export const demoResourceHistory: ResourceSample[] = Array.from({ length: 91 }, (_, index) => {
  const phase = index / 7
  const memoryUtilization = 42 + Math.sin(phase / 2) * 5
  const vramUtilization = 48 + Math.cos(phase / 1.6) * 7
  return {
    capturedAt: demoNow - (90 - index) * 10_000,
    cpuUtilization: 30 + Math.sin(phase) * 12,
    gpuUtilization: 72 + Math.cos(phase * 1.3) * 11,
    memoryUtilization,
    vramUtilization,
    memoryUsedBytes: memoryUtilization / 100 * demoSystem.memory_total_bytes,
    memoryTotalBytes: demoSystem.memory_total_bytes,
    vramUsedMb: vramUtilization / 100 * demoSystem.gpus[0].memory_total_mb,
    vramTotalMb: demoSystem.gpus[0].memory_total_mb,
  }
})

export const demoRenderUrl = demoRender
