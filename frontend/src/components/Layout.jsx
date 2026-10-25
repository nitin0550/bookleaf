import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useLiveUpdates } from '../hooks/useLiveUpdates'

const NAV = {
  author: [
    { to: '/books', label: 'My Books' },
    { to: '/tickets', label: 'My Tickets' },
    { to: '/tickets/new', label: 'New Query' },
  ],
  admin: [{ to: '/admin/tickets', label: 'Ticket Queue' }],
}

export default function Layout() {
  const { user, logout } = useAuth()
  const { connected } = useLiveUpdates(Boolean(user))

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
              <path d="M6 26C6 12 16 4 28 4c0 12-8 22-22 22z" fill="currentColor" />
            </svg>
            <span>BookLeaf</span>
            <span className="brand-sub">{user.role === 'admin' ? 'Support Desk' : 'Author Portal'}</span>
          </div>
          <nav className="nav">
            {NAV[user.role].map((n) => (
              <NavLink key={n.to} to={n.to} end className={({ isActive }) => (isActive ? 'active' : '')}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-right">
            <span className={`live ${connected ? 'on' : 'off'}`} title={connected ? 'Live updates on' : 'Reconnecting…'}>
              <span className="live-dot" /> {connected ? 'Live' : 'Offline'}
            </span>
            <span className="who">{user.full_name}</span>
            <button className="btn btn-ghost btn-sm" onClick={logout}>Sign out</button>
          </div>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
