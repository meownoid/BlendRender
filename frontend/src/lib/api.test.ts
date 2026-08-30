import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from './api'
import type { Job, RenderForm } from '../types'

class MockXMLHttpRequest {
  static instances: MockXMLHttpRequest[] = []

  readonly upload = new EventTarget()
  readonly events = new EventTarget()
  readonly open = vi.fn()
  readonly send = vi.fn()
  responseText = ''
  status = 0
  withCredentials = false

  constructor() {
    MockXMLHttpRequest.instances.push(this)
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (listener) this.events.addEventListener(type, listener)
  }

  emitProgress(loaded: number, total: number | null) {
    this.upload.dispatchEvent(new ProgressEvent('progress', {
      lengthComputable: total != null,
      loaded,
      total: total ?? 0,
    }))
  }

  finishUpload() {
    this.upload.dispatchEvent(new Event('load'))
  }

  respond(status: number, responseText: string) {
    this.status = status
    this.responseText = responseText
    this.events.dispatchEvent(new Event('load'))
  }

  fail() {
    this.events.dispatchEvent(new Event('error'))
  }
}

const job: Job = {
  id: 'job-1',
  filename: 'scene.blend',
  status: 'queued',
  mode: 'still',
  frame_start: 1,
  frame_end: 1,
  backend: 'CPU',
  samples: null,
  resolution_x: null,
  resolution_y: null,
  resolution_percentage: null,
  progress: 0,
  current_frame: null,
  sample_current: null,
  sample_total: null,
  completed_frames: [],
  error: null,
  log_tail: '',
  created_at: '2026-08-30T00:00:00Z',
  started_at: null,
  finished_at: null,
  elapsed_seconds: 0,
  eta_seconds: null,
  cancel_requested: false,
}

const form: RenderForm = {
  file: new File(['blend'], 'scene.blend'),
  mode: 'still',
  frame: 1,
  start: 1,
  end: 1,
  backend: 'CPU',
}

beforeEach(() => {
  MockXMLHttpRequest.instances = []
  vi.stubGlobal('XMLHttpRequest', MockXMLHttpRequest)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('uploads job fields with progress and resolves the created job', async () => {
  const onProgress = vi.fn()
  const pending = api.createJob(form, onProgress)
  const request = MockXMLHttpRequest.instances[0]

  expect(request.open).toHaveBeenCalledWith('POST', '/api/jobs')
  expect(request.withCredentials).toBe(true)
  const body = request.send.mock.calls[0][0] as FormData
  expect(body.get('file')).toBe(form.file)
  expect(body.get('mode')).toBe('still')
  expect(body.get('frame')).toBe('1')
  expect(body.get('backend')).toBe('CPU')

  request.emitProgress(2, 5)
  expect(onProgress).toHaveBeenLastCalledWith({ loaded: 2, total: 5 })
  request.finishUpload()
  expect(onProgress).toHaveBeenLastCalledWith({ loaded: form.file.size, total: form.file.size })
  request.respond(201, JSON.stringify(job))

  await expect(pending).resolves.toEqual(job)
})

test('returns the API error detail for a rejected upload', async () => {
  const pending = api.createJob(form)
  MockXMLHttpRequest.instances[0].respond(413, JSON.stringify({ detail: 'Upload exceeds the configured limit' }))

  await expect(pending).rejects.toMatchObject({
    message: 'Upload exceeds the configured limit',
    status: 413,
  })
})

test('reports network and malformed-response failures', async () => {
  const networkPending = api.createJob(form)
  MockXMLHttpRequest.instances[0].fail()
  await expect(networkPending).rejects.toMatchObject({ message: 'Unable to upload render', status: 0 })

  const malformedPending = api.createJob(form)
  MockXMLHttpRequest.instances[1].respond(201, 'not json')
  await expect(malformedPending).rejects.toMatchObject({
    message: 'Unable to read server response',
    status: 201,
  })
})
