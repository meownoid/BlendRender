import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { NewJobPanel } from './NewJobPanel'

test('submits an optional tile size override', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(
    <NewJobPanel
      open
      scene={{
        id: 'scene-1',
        filename: 'city.blend',
        name: 'City at night',
        source_kind: 'blend',
        entrypoint: 'city.blend',
        created_at: '2026-01-01T00:00:00Z',
        size_bytes: 100,
        job_count: 0,
        result_count: 0,
      }}
      system={{
        pod_id: 'pod-a',
        blender_version: '5.2.1',
        gpus: [],
        available_backends: ['CPU'],
        cpu_utilization: 0,
        memory_used_bytes: 0,
        memory_total_bytes: 1,
        disk_free_bytes: 1,
        disk_total_bytes: 1,
      }}
      busy={false}
      onClose={vi.fn()}
      onSubmit={onSubmit}
    />,
  )

  fireEvent.change(screen.getByLabelText('Tile size (optional)'), { target: { value: '256' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create job' }))

  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
    scene_id: 'scene-1',
    tile_size: 256,
  })))
})
