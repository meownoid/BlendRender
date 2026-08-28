import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { vi } from 'vitest'
import { LoginPage } from './LoginPage'

test('submits the configured password', async () => {
  const onLogin = vi.fn().mockResolvedValue(undefined)
  render(<LoginPage onLogin={onLogin} />)
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  await waitFor(() => expect(onLogin).toHaveBeenCalledWith('secret'))
})

test('shows login failures without replacing the form', async () => {
  render(<LoginPage onLogin={vi.fn().mockRejectedValue(new Error('Incorrect password'))} />)
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'bad' } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
  expect(await screen.findByText('Incorrect password')).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Open render node' })).toBeVisible()
})

