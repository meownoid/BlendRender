import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { api } from '../lib/api'
import { SceneWorkspace } from './SceneWorkspace'

vi.mock('../lib/api', () => ({
  api: {
    downloadSceneArchive: vi.fn(),
    resultImageUrl: (sceneId: string, resultId: string) => `/preview/${sceneId}/${resultId}`,
  },
}))

const scene = {
  id: 'scene-1',
  filename: 'city.blend',
  name: 'City at night',
  source_kind: 'blend' as const,
  entrypoint: 'input.blend',
  created_at: '2026-01-01T00:00:00Z',
  size_bytes: 100,
  job_count: 2,
  result_count: 2,
}

test('renders every result variant for a frame and downloads a selection', async () => {
  render(
    <SceneWorkspace
      scene={scene}
      jobs={[]}
      loading={false}
      onDelete={vi.fn().mockResolvedValue(undefined)}
      frames={[
        {
          frame: 12,
          results: [
            {
              id: 'result-cpu',
              scene_id: scene.id,
              job_id: 'job-1',
              frame: 12,
              pod_id: 'pod-cpu',
              backend: 'CPU',
              hardware: ['AMD EPYC'],
              samples: 32,
              render_seconds: 8.4,
              completed_at: '2026-01-01T00:01:00Z',
            },
            {
              id: 'result-gpu',
              scene_id: scene.id,
              job_id: 'job-2',
              frame: 12,
              pod_id: 'pod-gpu-with-a-very-long-name',
              backend: 'OPTIX',
              hardware: ['NVIDIA RTX 6000 Ada'],
              samples: 64,
              render_seconds: 2.1,
              completed_at: '2026-01-01T00:02:00Z',
            },
          ],
        },
      ]}
    />,
  )

  expect(screen.getByText('Frame 0012')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'City at night' })).toBeVisible()
  expect(screen.getByText('AMD EPYC')).toBeVisible()
  expect(screen.getByText('NVIDIA RTX 6000 Ada')).toBeVisible()
  expect(screen.getByText('64 samples')).toBeVisible()
  expect(screen.getByText('pod-gpu-with-a-v...')).toHaveAttribute('title', 'pod-gpu-with-a-very-long-name')

  fireEvent.click(screen.getByAltText('Frame 12, CPU render'))
  fireEvent.click(screen.getByRole('button', { name: 'Download 1' }))
  await waitFor(() => expect(api.downloadSceneArchive).toHaveBeenCalledWith(scene, ['result-cpu']))
})

test('shows download progress, disables the button, and reports an archive error', async () => {
  let rejectDownload: (reason: Error) => void = () => undefined
  vi.mocked(api.downloadSceneArchive).mockImplementationOnce(() => new Promise<void>((_, reject) => {
    rejectDownload = reject
  }))
  render(
    <SceneWorkspace
      scene={scene}
      jobs={[]}
      loading={false}
      onDelete={vi.fn().mockResolvedValue(undefined)}
      frames={[{ frame: 12, results: [{ id: 'result-cpu', scene_id: scene.id, job_id: 'job-1', frame: 12, pod_id: 'pod-cpu', backend: 'CPU', hardware: ['AMD EPYC'], samples: 32, render_seconds: 8.4, completed_at: '2026-01-01T00:01:00Z' }] }]}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Download all' }))
  expect(screen.getByRole('button', { name: 'Preparing download…' })).toBeDisabled()
  expect(screen.getByRole('status', { name: 'Preparing result archive' })).toBeVisible()

  rejectDownload(new Error('Archive service is unavailable'))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Archive service is unavailable'))
  expect(screen.getByRole('button', { name: 'Download all' })).toBeEnabled()
})

test('shows a loading state instead of stale or empty results', () => {
  render(
    <SceneWorkspace
      scene={scene}
      jobs={[]}
      loading
      onDelete={vi.fn().mockResolvedValue(undefined)}
      frames={[]}
    />,
  )

  expect(screen.getByRole('status')).toHaveTextContent('Loading scene results…')
  expect(screen.queryByText('Rendered frames from every pod will appear here.')).not.toBeInTheDocument()
})
