import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import type { Job, Scene } from '../types'
import { JobFilters } from './JobFilters'

const emptyJobFilters = { sceneId: '', status: '', backend: '', podId: '' } as const

const scenes: Scene[] = [
  { id: 'scene-1', filename: 'first.blend', source_kind: 'blend', entrypoint: 'first.blend', created_at: '2026-01-01T00:00:00Z', size_bytes: 100, job_count: 1, result_count: 0 },
  { id: 'scene-2', filename: 'second.blend', source_kind: 'blend', entrypoint: 'second.blend', created_at: '2026-01-01T00:00:00Z', size_bytes: 100, job_count: 1, result_count: 0 },
]

const jobs: Job[] = [
  { id: 'job-1', scene_id: 'scene-1', filename: 'first.blend', owner_pod_id: 'pod-a', owner_online: true, status: 'running', mode: 'still', frame_start: 1, frame_end: 1, backend: 'CPU', samples: null, resolution_x: null, resolution_y: null, resolution_percentage: null, progress: 50, current_frame: 1, sample_current: null, sample_total: null, completed_frames: [], error: null, log_tail: '', created_at: '2026-01-01T00:00:00Z', started_at: '2026-01-01T00:00:01Z', finished_at: null, elapsed_seconds: 1, eta_seconds: null, cancel_requested: false },
  { id: 'job-2', scene_id: 'scene-2', filename: 'second.blend', owner_pod_id: 'pod-b', owner_online: true, status: 'completed', mode: 'still', frame_start: 1, frame_end: 1, backend: 'OPTIX', samples: null, resolution_x: null, resolution_y: null, resolution_percentage: null, progress: 100, current_frame: 1, sample_current: null, sample_total: null, completed_frames: [1], error: null, log_tail: '', created_at: '2026-01-01T00:00:00Z', started_at: '2026-01-01T00:00:01Z', finished_at: '2026-01-01T00:00:02Z', elapsed_seconds: 1, eta_seconds: null, cancel_requested: false },
]

test('offers the shared job dimensions and updates the selected filter', () => {
  const onChange = vi.fn()
  render(<JobFilters jobs={jobs} scenes={scenes} filters={emptyJobFilters} onChange={onChange} />)

  fireEvent.change(screen.getByLabelText('Backend'), { target: { value: 'OPTIX' } })

  expect(screen.getByLabelText('Scene')).toHaveTextContent('first.blend')
  expect(screen.getByLabelText('Status')).toHaveTextContent('running')
  expect(screen.getByLabelText('Pod')).toHaveTextContent('pod-a')
  expect(onChange).toHaveBeenCalledWith({ ...emptyJobFilters, backend: 'OPTIX' })
})

test('clears all selected filters', () => {
  const onChange = vi.fn()
  render(<JobFilters jobs={jobs} scenes={scenes} filters={{ sceneId: 'scene-1', status: 'running', backend: 'CPU', podId: 'pod-a' }} onChange={onChange} />)

  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))

  expect(onChange).toHaveBeenCalledWith(emptyJobFilters)
})
