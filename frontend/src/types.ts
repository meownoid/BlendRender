export type Backend = 'OPTIX' | 'CUDA'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'canceled' | 'interrupted'

export interface Job {
  id: string
  filename: string
  status: JobStatus
  mode: 'still' | 'range'
  frame_start: number
  frame_end: number
  backend: Backend
  progress: number
  current_frame: number | null
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

export interface GPUInfo {
  name: string
  utilization: number
  memory_used_mb: number
  memory_total_mb: number
}

export interface SystemInfo {
  blender_version: string | null
  gpus: GPUInfo[]
  available_backends: Backend[]
  disk_free_bytes: number
  disk_total_bytes: number
}

export interface RenderForm {
  file: File
  mode: 'still' | 'range'
  frame: number
  start: number
  end: number
  backend: Backend
}

