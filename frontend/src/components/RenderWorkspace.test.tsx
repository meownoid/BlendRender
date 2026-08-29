import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { RenderWorkspace } from './RenderWorkspace'
import type { Job } from '../types'

const failedJob: Job = {
  id: 'job-1',
  filename: 'scene.blend',
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
  completed_frames: [],
  error: 'Unable to run Blender',
  log_tail: '',
  created_at: '2026-08-28T00:00:00Z',
  started_at: '2026-08-28T00:00:00Z',
  finished_at: '2026-08-28T00:00:01Z',
  elapsed_seconds: 1,
  eta_seconds: null,
  cancel_requested: false,
}

test('shows a terminal empty-preview state for a failed job', () => {
  const { container } = render(
    <RenderWorkspace job={failedJob} onCancel={vi.fn()} onRetry={vi.fn()} onDelete={vi.fn()} />,
  )

  expect(container.querySelector('.render-preview')).toHaveTextContent('Render failed')
  expect(screen.queryByText('First frame is rendering')).not.toBeInTheDocument()
  expect(container.querySelector('.render-preview--active')).toBeNull()
})
