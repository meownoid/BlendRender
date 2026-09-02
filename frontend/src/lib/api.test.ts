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

test('loads every frame page for a scene', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ frame: 200, results: [] }],
      next_cursor: 199,
    })))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{ frame: 198, results: [] }],
      next_cursor: null,
    })))

  await expect(api.allFrames('scene-1')).resolves.toEqual([
    { frame: 200, results: [] },
    { frame: 198, results: [] },
  ])
  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    '/api/scenes/scene-1/frames?limit=200',
    '/api/scenes/scene-1/frames?limit=200&cursor=199',
  ])
})
