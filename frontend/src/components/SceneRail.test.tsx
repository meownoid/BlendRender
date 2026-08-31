import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import type { Scene } from '../types'
import { SceneRail } from './SceneRail'

const scene: Scene = {
  id: 'scene-1',
  filename: 'forest.blend',
  name: 'Forest',
  source_kind: 'blend',
  entrypoint: 'forest.blend',
  created_at: '2026-08-31T00:00:00Z',
  size_bytes: Math.round(2.5 * 1024 ** 2),
  job_count: 1,
  result_count: 3,
}

test('shows an uploaded scene size in the scene rail', () => {
  render(<SceneRail scenes={[scene]} selectedId={null} onSelect={vi.fn()} onUpload={vi.fn()} />)

  expect(screen.getByText('2.5 MB · 3 results · 1 jobs')).toBeInTheDocument()
})
