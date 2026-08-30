import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { NewRenderPanel } from './NewRenderPanel'
import type { SystemInfo } from '../types'

const cpuOnlySystem: SystemInfo = {
  blender_version: '5.2.1',
  gpus: [],
  available_backends: ['CPU'],
  cpu_utilization: 20,
  memory_used_bytes: 4 * 1024 ** 3,
  memory_total_bytes: 16 * 1024 ** 3,
  disk_free_bytes: 1,
  disk_total_bytes: 2,
}

test('selects CPU when it is the only available backend and submits it', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  const { container } = render(<NewRenderPanel open system={cpuOnlySystem} busy={false} uploadProgress={null} onClose={vi.fn()} onSubmit={onSubmit} />)
  expect(container.querySelector('form')).toHaveAttribute('data-1p-ignore', 'true')
  expect(screen.getByRole('button', { name: 'CPU' })).toHaveClass('is-selected')
  expect(screen.getByRole('button', { name: 'OptiX' })).toBeDisabled()
  const input = container.querySelector('input[type="file"]')
  expect(input).not.toBeNull()
  fireEvent.change(input as HTMLInputElement, { target: { files: [new File(['blend'], 'scene.blend')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Queue render' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ backend: 'CPU' })))
})

test('accepts a project ZIP archive', async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  const { container } = render(<NewRenderPanel open system={cpuOnlySystem} busy={false} uploadProgress={null} onClose={vi.fn()} onSubmit={onSubmit} />)
  const input = container.querySelector('input[type="file"]')
  expect(input).toHaveAttribute('accept', '.blend,.zip')
  fireEvent.change(input as HTMLInputElement, { target: { files: [new File(['zip'], 'project.zip')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Queue render' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalled())
  expect((onSubmit.mock.calls[0][0] as { file: File }).file.name).toBe('project.zip')
})

test('shows upload progress and disables render controls', () => {
  render(
    <NewRenderPanel
      open
      system={cpuOnlySystem}
      busy
      uploadProgress={{ loaded: 3 * 1024 ** 2, total: 10 * 1024 ** 2 }}
      onClose={vi.fn()}
      onSubmit={vi.fn()}
    />,
  )

  expect(screen.getByText('Uploading 30%')).toBeVisible()
  expect(screen.getByText('3 MB / 10 MB')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'Upload progress' })).toHaveAttribute('aria-valuenow', '30')
  expect(screen.getByRole('button', { name: 'Close new render panel' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Still' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Uploading…' })).toBeDisabled()
})

test('shows finalizing and indeterminate upload states', () => {
  const { rerender } = render(
    <NewRenderPanel
      open
      system={cpuOnlySystem}
      busy
      uploadProgress={{ loaded: 10 * 1024 ** 2, total: 10 * 1024 ** 2 }}
      onClose={vi.fn()}
      onSubmit={vi.fn()}
    />,
  )

  expect(screen.getByText('Finalizing upload…')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'Upload progress' })).toHaveAttribute('aria-valuenow', '100')

  rerender(
    <NewRenderPanel
      open
      system={cpuOnlySystem}
      busy
      uploadProgress={{ loaded: 1024 ** 2, total: null }}
      onClose={vi.fn()}
      onSubmit={vi.fn()}
    />,
  )

  expect(screen.getByRole('status')).toHaveTextContent('Uploading…')
  expect(screen.getByText('1 MB uploaded')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'Upload progress' })).not.toHaveAttribute('aria-valuenow')
})
