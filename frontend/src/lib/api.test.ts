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
