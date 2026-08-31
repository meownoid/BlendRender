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
  UploadSession,
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

interface UploadOptions {
  onProgress?: (progress: UploadProgress) => void
  onSession?: (sessionId: string) => void
  signal?: AbortSignal
}

interface UploadDraft {
  version: 1
  sessionId: string
  filename: string
  size: number
  lastModified: number
}

const UPLOAD_DRAFT_STORAGE_KEY = 'blendrender-upload-draft-v1'
const MAX_UPLOAD_RETRIES = 3

function uploadScene(file: File, name: string, options: UploadOptions = {}): Promise<Scene> {
  return resumeOrCreateUpload(file, name, options)
}

function sendUploadChunk(
  uploadId: string,
  offset: number,
  chunk: Blob,
  total: number,
  options: UploadOptions,
): Promise<UploadSession> {
  return new Promise((resolve, reject) => {
    const response = new XMLHttpRequest()
    const finish = (callback: () => void) => {
      options.signal?.removeEventListener('abort', abort)
      callback()
    }
    const abort = () => response.abort()
    if (options.signal?.aborted) return reject(new ApiError('Upload canceled', 0))
    response.open('PATCH', `/api/uploads/${uploadId}`)
    response.withCredentials = true
    response.setRequestHeader('Content-Type', 'application/octet-stream')
    response.setRequestHeader('Upload-Offset', String(offset))
    response.upload.addEventListener('progress', (event) => {
      options.onProgress?.({
        loaded: offset + event.loaded,
        total: event.lengthComputable ? total : null,
        phase: 'uploading',
      })
    })
    response.addEventListener('error', () => finish(() => reject(new ApiError('Unable to upload scene', 0))))
    response.addEventListener('abort', () => finish(() => reject(new ApiError('Upload canceled', 0))))
    response.addEventListener('load', () => {
      if (response.status < 200 || response.status >= 300) return finish(() => reject(responseError(response)))
      try {
        finish(() => resolve(JSON.parse(response.responseText) as UploadSession))
      } catch {
        finish(() => reject(new ApiError('Unable to read server response', response.status)))
      }
    })
    options.signal?.addEventListener('abort', abort, { once: true })
    response.send(chunk)
  })
}

async function resumeOrCreateUpload(
  file: File,
  name: string,
  options: UploadOptions,
): Promise<Scene> {
  let upload = await matchingUpload(file)
  if (upload == null) {
    upload = await request<UploadSession>('/api/uploads', {
      method: 'POST',
      body: JSON.stringify({ filename: file.name, name: name.trim() || null, size_bytes: file.size }),
      signal: options.signal,
    })
    saveUploadDraft(file, upload.id)
  }
  options.onSession?.(upload.id)
  options.onProgress?.({
    loaded: upload.uploaded_bytes,
    total: upload.size_bytes,
    phase: upload.status === 'finalizing' ? 'finalizing' : 'uploading',
  })
  if (upload.status === 'completed' && upload.scene != null) {
    clearUploadDraft(upload.id)
    return upload.scene
  }

  let offset = upload.uploaded_bytes
  while (offset < file.size) {
    throwIfAborted(options.signal)
    const chunk = file.slice(offset, Math.min(offset + upload.chunk_size_bytes, file.size))
    let retries = 0
    while (true) {
      try {
        upload = await sendUploadChunk(upload.id, offset, chunk, file.size, options)
        offset = upload.uploaded_bytes
        break
      } catch (reason) {
        if (!isRetryableUploadError(reason) || retries >= MAX_UPLOAD_RETRIES) throw reason
        retries += 1
        options.onProgress?.({ loaded: offset, total: file.size, phase: 'retrying' })
        await delay(250 * 2 ** (retries - 1), options.signal)
        upload = await request<UploadSession>(`/api/uploads/${upload.id}`, {
          signal: options.signal,
        })
        if (upload.status !== 'uploading') break
        offset = upload.uploaded_bytes
      }
    }
    if (upload.status !== 'uploading') break
  }

  if (upload.status === 'uploading' || upload.status === 'failed') {
    upload = await request<UploadSession>(`/api/uploads/${upload.id}/complete`, {
      method: 'POST',
      body: '{}',
      signal: options.signal,
    })
  }
  return waitForUploadCompletion(upload, options)
}

async function matchingUpload(file: File): Promise<UploadSession | null> {
  const draft = readUploadDraft()
  if (
    draft == null
    || draft.filename !== file.name
    || draft.size !== file.size
    || draft.lastModified !== file.lastModified
  ) return null
  try {
    const upload = await request<UploadSession>(`/api/uploads/${draft.sessionId}`)
    return upload.size_bytes === file.size ? upload : null
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 404) clearUploadDraft(draft.sessionId)
    return null
  }
}

async function waitForUploadCompletion(
  initial: UploadSession,
  options: UploadOptions,
): Promise<Scene> {
  let upload = initial
  while (true) {
    throwIfAborted(options.signal)
    if (upload.status === 'completed' && upload.scene != null) {
      clearUploadDraft(upload.id)
      return upload.scene
    }
    if (upload.status === 'failed') {
      throw new ApiError(upload.error ?? 'Unable to finalize the uploaded project', 422)
    }
    options.onProgress?.({
      loaded: upload.uploaded_bytes,
      total: upload.size_bytes,
      phase: 'finalizing',
    })
    await delay(1000, options.signal)
    upload = await request<UploadSession>(`/api/uploads/${upload.id}`, { signal: options.signal })
  }
}

function readUploadDraft(): UploadDraft | null {
  try {
    const value = JSON.parse(localStorage.getItem(UPLOAD_DRAFT_STORAGE_KEY) ?? 'null') as Partial<UploadDraft> | null
    if (
      value?.version === 1
      && typeof value.sessionId === 'string'
      && typeof value.filename === 'string'
      && typeof value.size === 'number'
      && typeof value.lastModified === 'number'
    ) return value as UploadDraft
  } catch {
    // Invalid browser storage is equivalent to no saved upload draft.
  }
  return null
}

function saveUploadDraft(file: File, sessionId: string) {
  const draft: UploadDraft = {
    version: 1,
    sessionId,
    filename: file.name,
    size: file.size,
    lastModified: file.lastModified,
  }
  localStorage.setItem(UPLOAD_DRAFT_STORAGE_KEY, JSON.stringify(draft))
}

function clearUploadDraft(sessionId: string) {
  if (readUploadDraft()?.sessionId === sessionId) localStorage.removeItem(UPLOAD_DRAFT_STORAGE_KEY)
}

function isRetryableUploadError(reason: unknown): boolean {
  return !(reason instanceof ApiError && reason.status >= 400 && reason.status < 500 && reason.status !== 409)
}

function throwIfAborted(signal: AbortSignal | undefined) {
  if (signal?.aborted) throw new ApiError('Upload canceled', 0)
}

function delay(milliseconds: number, signal: AbortSignal | undefined): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, milliseconds)
    const abort = () => {
      window.clearTimeout(timer)
      reject(new ApiError('Upload canceled', 0))
    }
    signal?.addEventListener('abort', abort, { once: true })
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
  deleteUpload: (id: string) => request<void>(`/api/uploads/${id}`, { method: 'DELETE' }),
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
