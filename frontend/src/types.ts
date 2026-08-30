export type Backend = 'OPTIX' | 'CUDA' | 'CPU'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'canceled' | 'interrupted'

export interface Scene {
  id: string
  filename: string
  source_kind: 'blend' | 'zip'
  entrypoint: string
  created_at: string
  size_bytes: number
  job_count: number
  result_count: number
}

export interface Job {
  id: string
  scene_id: string
  filename: string
  owner_pod_id: string
  owner_online: boolean
  status: JobStatus
  mode: 'still' | 'range'
  frame_start: number
  frame_end: number
  backend: Backend
  samples: number | null
  resolution_x: number | null
  resolution_y: number | null
  resolution_percentage: number | null
  progress: number
  current_frame: number | null
  sample_current: number | null
  sample_total: number | null
  completed_frames: number[]
  error: string | null
  log_tail: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  elapsed_seconds: number
  eta_seconds: number | null
  cancel_requested: boolean
}

export interface FrameResult {
  id: string
  scene_id: string
  job_id: string
  frame: number
  pod_id: string
  backend: Backend
  hardware: string[]
  samples: number
  render_seconds: number
  completed_at: string
}

export interface FrameGroup {
  frame: number
  results: FrameResult[]
}

export interface FramesPage {
  items: FrameGroup[]
  next_cursor: number | null
}

export interface GPUInfo {
  name: string
  utilization: number
  memory_used_mb: number
  memory_total_mb: number
}

export interface SystemInfo {
  pod_id: string
  blender_version: string | null
  gpus: GPUInfo[]
  available_backends: Backend[]
  cpu_utilization: number
  memory_used_bytes: number
  memory_total_bytes: number
  disk_free_bytes: number
  disk_total_bytes: number
}

export interface TelemetrySample {
  captured_at: string
  cpu_utilization: number
  gpu_utilization: number | null
  memory_used_bytes: number
  memory_total_bytes: number
  vram_used_mb: number | null
  vram_total_mb: number | null
}

export interface CreateJobForm {
  scene_id: string
  mode: 'still' | 'range'
  frame: number
  start: number
  end: number
  backend: Backend
  samples?: number
  resolution_x?: number
  resolution_y?: number
  resolution_percentage?: number
}

export interface UploadProgress {
  loaded: number
  total: number | null
}
