import { useEffect, useState } from 'react'
import { ApiError, api } from './lib/api'
import { Dashboard } from './components/Dashboard'
import { LoginPage } from './components/LoginPage'

const demoMode = import.meta.env.DEV && new URLSearchParams(window.location.search).has('demo')

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(demoMode ? true : null)

  useEffect(() => {
    if (demoMode) return
    api.session()
      .then(({ authenticated: value }) => setAuthenticated(value))
      .catch(() => setAuthenticated(false))
  }, [])

  async function login(password: string) {
    try {
      await api.login(password)
      setAuthenticated(true)
    } catch (reason) {
      if (reason instanceof ApiError) throw new Error(reason.message)
      throw reason
    }
  }

  async function logout() {
    if (!demoMode) await api.logout()
    setAuthenticated(false)
  }

  if (authenticated === null) return <div className="boot-screen"><span className="boot-screen__spinner" /><span>Opening BlendQueue</span></div>
  if (!authenticated) return <LoginPage onLogin={login} />
  return <Dashboard demo={demoMode} onLogout={logout} />
}

