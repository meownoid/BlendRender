import type {
  CreateJobForm,
  FrameResult,
  FramesPage,
  Job,
  JobStatus,
  Scene,
  SystemInfo,
  TelemetrySample,
  UploadProgress,
} from '../types'

export class ApiError extends Error {
  constructor(message: string, public status: number) {
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

function responseError(response: XMLHttpRequest): ApiError {
  try {
    const payload = JSON.parse(response.responseText) as { detail?: unknown }
    return new ApiError(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`, response.status)
  } catch {
    return new ApiError(`Request failed (${response.status})`, response.status)
  }
}

function uploadScene(file: File, name: string, onProgress?: (progress: UploadProgress) => void): Promise<Scene> {
  return new Promise((resolve, reject) => {
    const response = new XMLHttpRequest()
    response.open('POST', '/api/scenes')
    response.withCredentials = true
    response.upload.addEventListener('progress', (event) => onProgress?.({ loaded: event.loaded, total: event.lengthComputable ? event.total : null }))
    response.addEventListener('error', () => reject(new ApiError('Unable to upload scene', 0)))
    response.addEventListener('load', () => {
      if (response.status < 200 || response.status >= 300) return reject(responseError(response))
      try { resolve(JSON.parse(response.responseText) as Scene) } catch { reject(new ApiError('Unable to read server response', response.status)) }
    })
    const body = new FormData()
    body.append('file', file)
    if (name.trim()) body.append('name', name)
    response.send(body)
  })
}

export const api = {
  session: () => request<{ authenticated: boolean }>('/api/auth/session'),
  login: (password: string) => request<{ authenticated: boolean }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/auth/logout', { method: 'POST', body: '{}' }),
  system: () => request<SystemInfo>('/api/system'),
  telemetry: () => request<TelemetrySample[]>('/api/system/telemetry'),
  scenes: () => request<Scene[]>('/api/scenes'),
  scene: (id: string) => request<Scene>(`/api/scenes/${id}`),
  uploadScene,
  deleteScene: (id: string) => request<void>(`/api/scenes/${id}`, { method: 'DELETE' }),
  jobs: (sceneId?: string, status?: JobStatus) => {
    const params = new URLSearchParams()
    if (sceneId) params.set('scene_id', sceneId)
    if (status) params.set('status', status)
    return request<Job[]>(`/api/jobs${params.size ? `?${params}` : ''}`)
  },
  createJob: (form: CreateJobForm) => request<Job>('/api/jobs', { method: 'POST', body: JSON.stringify(form) }),
  cancel: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST', body: '{}' }),
  retry: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: 'POST', body: '{}' }),
  deleteJob: (id: string) => request<void>(`/api/jobs/${id}`, { method: 'DELETE' }),
  frames: (sceneId: string, cursor?: number) => request<FramesPage>(`/api/scenes/${sceneId}/frames${cursor == null ? '' : `?cursor=${cursor}`}`),
  result: (sceneId: string, resultId: string) => request<FrameResult>(`/api/scenes/${sceneId}/results/${resultId}`),
  resultImageUrl: (sceneId: string, resultId: string, preview = false) => `/api/scenes/${sceneId}/results/${resultId}/image${preview ? '?preview=true' : ''}`,
  downloadSceneArchive: async (scene: Scene, resultIds?: string[]) => {
    const response = await fetch(`/api/scenes/${scene.id}/archive`, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ result_ids: resultIds?.length ? resultIds : null }),
    })
    if (!response.ok) throw responseError({ status: response.status, responseText: await response.text() } as XMLHttpRequest)
    const blob = await response.blob()
    downloadBlob(blob, `${scene.name.replace(/\.blend$/i, '')}-results.zip`)
  },
  downloadJobArchive: async (job: Job) => {
    const response = await fetch(`/api/jobs/${job.id}/archive`, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}',
    })
    if (!response.ok) throw responseError({ status: response.status, responseText: await response.text() } as XMLHttpRequest)
    downloadBlob(await response.blob(), `${job.filename.replace(/\.blend$/i, '')}-job-${job.id.slice(0, 8)}.zip`)
  },
}

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(url)
}
