import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import type { Job, Scene } from '../types'
import { JobsView } from './JobsView'

const scene: Scene = {
  id: 'scene-1',
  filename: 'input.blend',
  name: 'City at night',
  source_kind: 'blend',
  entrypoint: 'input.blend',
  created_at: '2026-01-01T00:00:00Z',
  size_bytes: 100,
  job_count: 1,
  result_count: 0,
}

const failedJob: Job = {
  id: 'job-1',
  scene_id: scene.id,
  filename: scene.filename,
  owner_pod_id: 'local',
  owner_online: true,
  status: 'failed',
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
  error: 'Blender exited before rendering frame 1.',
  log_tail: 'Error: Cannot read input.blend',
  created_at: '2026-01-01T00:00:00Z',
  started_at: '2026-01-01T00:00:01Z',
  finished_at: '2026-01-01T00:00:02Z',
  elapsed_seconds: 1,
  eta_seconds: null,
  cancel_requested: false,
}

test('opens a failed job to show its failure reason and log', () => {
  render(
    <JobsView
      jobs={[failedJob]}
      scenes={[scene]}
      podId="local"
      onCancel={vi.fn().mockResolvedValue(undefined)}
      onRetry={vi.fn().mockResolvedValue(undefined)}
      onDelete={vi.fn().mockResolvedValue(undefined)}
    />,
  )

  const row = screen.getByRole('row', { name: /City at night.*failed/i })
  expect(screen.queryByText('Failure details')).not.toBeInTheDocument()

  fireEvent.click(row)

  expect(row).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByText('Failure details')).toBeVisible()
  expect(screen.getByText('Blender exited before rendering frame 1.')).toBeVisible()
  expect(screen.getByText('Error: Cannot read input.blend')).toBeVisible()
})

test('opens and closes job details with the keyboard', () => {
  render(
    <JobsView
      jobs={[failedJob]}
      scenes={[scene]}
      podId="local"
      onCancel={vi.fn().mockResolvedValue(undefined)}
      onRetry={vi.fn().mockResolvedValue(undefined)}
      onDelete={vi.fn().mockResolvedValue(undefined)}
    />,
  )

  const row = screen.getByRole('row', { name: /City at night.*failed/i })
  fireEvent.keyDown(row, { key: 'Enter' })
  expect(screen.getByText('Failure details')).toBeVisible()

  fireEvent.keyDown(row, { key: ' ' })
  expect(screen.queryByText('Failure details')).not.toBeInTheDocument()
})
