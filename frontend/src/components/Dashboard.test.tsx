import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { Dashboard } from './Dashboard'

test('renders the approved demo workflow and filters jobs', () => {
  render(<Dashboard demo onLogout={vi.fn()} />)
  expect(screen.getByRole('heading', { name: 'studio_scene.blend' })).toBeVisible()
  expect(screen.getByText('Rendering frame 56 of 120')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Completed' }))
  expect(screen.getByText('hero_still.blend')).toBeVisible()
  expect(screen.queryByText('product_turntable.blend')).not.toBeInTheDocument()
})

test('closes and reopens the new render panel', () => {
  render(<Dashboard demo onLogout={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Close new render panel' }))
  expect(screen.queryByRole('button', { name: 'Close new render panel' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'New render' }))
  expect(screen.getByRole('button', { name: 'Close new render panel' })).toBeVisible()
})
