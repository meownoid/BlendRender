import demoRender from '../assets/demo-render.png'
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
  available_backends: ['OPTIX', 'CUDA'],
  disk_free_bytes: 68 * 1024 ** 3,
  disk_total_bytes: 100 * 1024 ** 3,
}

export const demoRenderUrl = demoRender
