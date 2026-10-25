import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ErrorBanner } from '../components/ui'

const DEMO = [
  { label: 'Author · Priya Sharma', email: 'priya.sharma@email.com', password: 'author123' },
  { label: 'Author · Sneha Kulkarni (book in production)', email: 'sneha.kulkarni@email.com', password: 'author123' },
  { label: 'Author · Ananya Reddy (never paid)', email: 'ananya.reddy@email.com', password: 'author123' },
  { label: 'Staff · Aisha Verma', email: 'admin@bookleaf.com', password: 'admin123' },
]

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await login(email.trim(), password)
      navigate(user.role === 'admin' ? '/admin/tickets' : '/books', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="brand brand-lg">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <path d="M6 26C6 12 16 4 28 4c0 12-8 22-22 22z" fill="currentColor" />
          </svg>
          <span>BookLeaf</span>
        </div>
        <h1>Author Support</h1>
        <p className="muted">Sign in to see your books, royalties and support conversations.</p>

        <form onSubmit={submit} className="form">
          <label>
            Email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Password
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          <ErrorBanner error={error} />
          <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>

        <div className="demo">
          <p className="demo-title">Demo accounts</p>
          {DEMO.map((d) => (
            <button key={d.email} type="button" className="demo-item" onClick={() => { setEmail(d.email); setPassword(d.password) }}>
              <span>{d.label}</span>
              <code>{d.email}</code>
            </button>
          ))}
          <p className="muted small">All authors from the sample dataset use password <code>author123</code>.</p>
        </div>
      </div>
    </div>
  )
}
