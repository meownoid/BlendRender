import { afterEach, expect, test, vi } from 'vitest'
import { api } from './api'

afterEach(() => vi.restoreAllMocks())

test('formats FastAPI validation errors for render settings', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    detail: [{
      type: 'less_than_equal',
      loc: ['body', 'resolution_percentage'],
      msg: 'Input should be less than or equal to 100',
      input: 4096,
    }],
  }), { status: 422, headers: { 'Content-Type': 'application/json' } }))

  await expect(api.createJob({
    scene_id: 'scene-1',
    mode: 'range',
    frame: 1,
    start: 1,
    end: 120,
    backend: 'CPU',
    resolution_percentage: 4096,
  })).rejects.toMatchObject({
    message: 'Resolution scale: Input should be less than or equal to 100',
    status: 422,
  })
})

test('loads one result page at a time for a scene', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    items: [{ frame: 200, results: [] }],
    next_cursor: 199,
  })))

  await expect(api.frames('scene-1', 199)).resolves.toEqual({
    items: [{ frame: 200, results: [] }],
    next_cursor: 199,
  })
  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    '/api/scenes/scene-1/frames?limit=50&cursor=199',
  ])
})

test('starts a native archive download without buffering the ZIP in JavaScript', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    download_url: '/api/archives/archive-1',
  })))
  const responseBlob = vi.spyOn(Response.prototype, 'blob')
  let downloadedUrl: string | null = null
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    downloadedUrl = this.getAttribute('href')
  })

  await api.downloadSceneArchive({
    id: 'scene-1',
    filename: 'city.blend',
    name: 'City at night',
    source_kind: 'blend',
    entrypoint: 'input.blend',
    created_at: '2026-01-01T00:00:00Z',
    size_bytes: 100,
    job_count: 0,
    result_count: 1,
  })

  expect(fetchMock).toHaveBeenCalledWith('/api/scenes/scene-1/archive', expect.objectContaining({
    method: 'POST',
  }))
  expect(responseBlob).not.toHaveBeenCalled()
  expect(click).toHaveBeenCalledOnce()
  expect(downloadedUrl).toBe('/api/archives/archive-1')
  expect(document.querySelector('a[href="/api/archives/archive-1"]')).toBeNull()
})
