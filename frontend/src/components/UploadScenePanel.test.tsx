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
