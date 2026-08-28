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
  const { container } = render(<NewRenderPanel open system={cpuOnlySystem} busy={false} onClose={vi.fn()} onSubmit={onSubmit} />)
  expect(screen.getByRole('button', { name: 'CPU' })).toHaveClass('is-selected')
  expect(screen.getByRole('button', { name: 'OptiX' })).toBeDisabled()
  const input = container.querySelector('input[type="file"]')
  expect(input).not.toBeNull()
  fireEvent.change(input as HTMLInputElement, { target: { files: [new File(['blend'], 'scene.blend')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Queue render' }))
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ backend: 'CPU' })))
})
