import { Eye, EyeOff } from 'lucide-react'
import { FormEvent, useState } from 'react'
import loginRender from '../assets/login-render.png'
import { Brand } from './Brand'

interface LoginPageProps {
  onLogin: (password: string) => Promise<void>
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await onLogin(password)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to open this render node')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-shell">
      <img className="login-shell__image" src={loginRender} alt="" />
      <div className="login-shell__shade" />
      <header className="login-shell__brand"><Brand /></header>
      <form className="login-form" onSubmit={submit}>
        <h1>Open render node</h1>
        <p>Enter the access password configured for this pod.</p>
        <label htmlFor="password">Password</label>
        <div className={`password-control${error ? ' password-control--error' : ''}`}>
          <input
            id="password"
            type={visible ? 'text' : 'password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
            autoComplete="current-password"
            data-1p-ignore="true"
            aria-describedby={error ? 'login-error' : undefined}
          />
          <button type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? 'Hide password' : 'Show password'}>
            {visible ? <EyeOff size={21} /> : <Eye size={21} />}
          </button>
        </div>
        <div className="login-form__message" id="login-error" role="alert">{error}</div>
        <button className="button button--primary login-form__submit" disabled={!password || submitting}>
          {submitting ? 'Opening…' : 'Continue'}
        </button>
      </form>
      <footer className="login-shell__footer">Blender 5.2 LTS <span>·</span> GPU node</footer>
    </main>
  )
}
