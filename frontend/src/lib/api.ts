import type { Job, JobStatus, RenderForm, SystemInfo, TelemetrySample, UploadProgress } from '../types'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(payload?.detail ?? `Request failed (${response.status})`, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function jobFormData(form: RenderForm): FormData {
  const body = new FormData()
  body.append('file', form.file)
  body.append('mode', form.mode)
  body.append('backend', form.backend)
  if (form.mode === 'still') body.append('frame', String(form.frame))
  else {
    body.append('start', String(form.start))
    body.append('end', String(form.end))
  }
  if (form.samples != null) body.append('samples', String(form.samples))
  if (form.resolution_x != null) body.append('resolution_x', String(form.resolution_x))
  if (form.resolution_y != null) body.append('resolution_y', String(form.resolution_y))
  if (form.resolution_percentage != null) body.append('resolution_percentage', String(form.resolution_percentage))
  return body
}

function responseError(response: XMLHttpRequest): ApiError {
  const payload = (() => {
    try {
      return JSON.parse(response.responseText) as { detail?: unknown }
    } catch {
      return null
    }
  })()
  const message = typeof payload?.detail === 'string'
    ? payload.detail
    : `Request failed (${response.status})`
  return new ApiError(message, response.status)
}

function uploadJob(form: RenderForm, onProgress?: (progress: UploadProgress) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const response = new XMLHttpRequest()
    response.open('POST', '/api/jobs')
    response.withCredentials = true
    response.upload.addEventListener('progress', (event) => {
      onProgress?.({ loaded: event.loaded, total: event.lengthComputable ? event.total : null })
    })
    response.upload.addEventListener('load', () => {
      onProgress?.({ loaded: form.file.size, total: form.file.size })
    })
    response.addEventListener('error', () => reject(new ApiError('Unable to upload render', 0)))
    response.addEventListener('abort', () => reject(new ApiError('Upload was interrupted', 0)))
    response.addEventListener('load', () => {
      if (response.status < 200 || response.status >= 300) {
        reject(responseError(response))
        return
      }
      try {
        resolve(JSON.parse(response.responseText) as Job)
      } catch {
        reject(new ApiError('Unable to read server response', response.status))
      }
    })
    response.send(jobFormData(form))
  })
}

export const api = {
  session: () => request<{ authenticated: boolean }>('/api/auth/session'),
  login: (password: string) =>
    request<{ authenticated: boolean }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  logout: () => request('/api/auth/logout', { method: 'POST', body: '{}' }),
  system: () => request<SystemInfo>('/api/system'),
  telemetry: () => request<TelemetrySample[]>('/api/system/telemetry'),
  jobs: (status?: JobStatus) => request<Job[]>(`/api/jobs${status ? `?status=${status}` : ''}`),
  createJob: (form: RenderForm, onProgress?: (progress: UploadProgress) => void) =>
    uploadJob(form, onProgress),
  cancel: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST', body: '{}' }),
  retry: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST', body: '{}' }),
  delete: (id: string) => request<void>(`/api/jobs/${id}`, { method: 'DELETE', body: '{}' }),
  frameUrl: (id: string, frame: number, preview = false) =>
    `/api/jobs/${id}/frames/${frame}${preview ? '?preview=true' : ''}`,
  downloadArchive: async (job: Job, frames?: number[]) => {
    const response = await fetch(`/api/jobs/${job.id}/archive`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ frames: frames?.length ? frames : null }),
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new ApiError(payload?.detail ?? 'Unable to download frames', response.status)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${job.filename.replace(/\.blend$/i, '')}-frames.zip`
    anchor.click()
    URL.revokeObjectURL(url)
  },
}
