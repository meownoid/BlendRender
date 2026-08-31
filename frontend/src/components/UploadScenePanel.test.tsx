import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { UploadScenePanel } from './UploadScenePanel'

test('submits an optional scene name with the selected file', async () => {
  const onUpload = vi.fn().mockResolvedValue(undefined)
  const { container } = render(
    <UploadScenePanel
      open
      busy={false}
      progress={null}
      onClose={vi.fn()}
      onUpload={onUpload}
    />,
  )
  const file = new File(['blend'], 'forest.blend')

  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [file] },
  })
  fireEvent.change(screen.getByLabelText('Name (optional)'), { target: { value: 'Forest' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create scene' }))

  await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file, 'Forest'))
})

test('submits a file dropped onto the upload area', async () => {
  const onUpload = vi.fn().mockResolvedValue(undefined)
  render(
    <UploadScenePanel
      open
      busy={false}
      progress={null}
      onClose={vi.fn()}
      onUpload={onUpload}
    />,
  )
  const file = new File(['blend'], 'forest.blend')
  const dropzone = screen.getByRole('button', { name: /Choose a \.blend or project ZIP/i })

  fireEvent.dragOver(dropzone, { dataTransfer: { dropEffect: 'none', files: [file] } })
  fireEvent.drop(dropzone, { dataTransfer: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: 'Create scene' }))

  await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file, ''))
})

test('allows cancelling an in-progress chunk upload but not finalization', () => {
  const onCancel = vi.fn()
  const { rerender } = render(
    <UploadScenePanel
      open
      busy
      progress={{ loaded: 4, total: 10, phase: 'uploading' }}
      onClose={vi.fn()}
      onCancel={onCancel}
      onUpload={vi.fn()}
    />,
  )

  fireEvent.click(screen.getByRole('button', { name: 'Cancel upload' }))
  expect(onCancel).toHaveBeenCalledOnce()

  rerender(
    <UploadScenePanel
      open
      busy
      progress={{ loaded: 10, total: 10, phase: 'finalizing' }}
      onClose={vi.fn()}
      onCancel={onCancel}
      onUpload={vi.fn()}
    />,
  )
  expect(screen.queryByRole('button', { name: 'Cancel upload' })).toBeNull()
  expect(screen.getByText('Validating and unpacking…')).toBeInTheDocument()
})

test('shows transferred and total bytes beside upload progress', () => {
  render(
    <UploadScenePanel
      open
      busy
      progress={{ loaded: 4 * 1024 ** 2, total: 10 * 1024 ** 2, phase: 'uploading' }}
      onClose={vi.fn()}
      onUpload={vi.fn()}
    />,
  )

  expect(screen.getByText('Uploading 40%')).toBeInTheDocument()
  expect(screen.getByText('4.0 MB / 10 MB')).toBeInTheDocument()
})
