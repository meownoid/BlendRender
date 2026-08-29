import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { Dashboard } from './Dashboard'

test('hydrates system charts from server telemetry', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const payload = String(input).endsWith('/api/jobs')
      ? []
      : String(input).endsWith('/api/system/telemetry')
        ? [{
            captured_at: '2026-08-29T12:00:00.000Z',
            cpu_utilization: 45,
            gpu_utilization: null,
            memory_used_bytes: 6 * 1024 ** 3,
            memory_total_bytes: 16 * 1024 ** 3,
            vram_used_mb: null,
            vram_total_mb: null,
          }]
        : {
            blender_version: '5.2.1',
            gpus: [],
            available_backends: ['CPU'],
            cpu_utilization: 45,
            memory_used_bytes: 6 * 1024 ** 3,
            memory_total_bytes: 16 * 1024 ** 3,
            disk_free_bytes: 1,
            disk_total_bytes: 2,
          }
    return { ok: true, status: 200, json: async () => payload } as Response
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<Dashboard onLogout={vi.fn()} />)

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
  expect(fetchMock).toHaveBeenCalledWith('/api/system/telemetry', expect.anything())
  expect(screen.getByRole('button', { name: /Open system stats\. CPU 45%/ })).toBeVisible()
  vi.unstubAllGlobals()
})
