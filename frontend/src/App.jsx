import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Login from './pages/Login'
import MyBooks from './pages/author/MyBooks'
import MyTickets from './pages/author/MyTickets'
import NewTicket from './pages/author/NewTicket'
import AuthorTicket from './pages/author/AuthorTicket'
import Queue from './pages/admin/Queue'
import AdminTicket from './pages/admin/AdminTicket'

function RequireRole({ role, children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== role) return <Navigate to={user.role === 'admin' ? '/admin/tickets' : '/books'} replace />
  return children
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <div className="center-page"><Spinner /></div>

  const home = !user ? '/login' : user.role === 'admin' ? '/admin/tickets' : '/books'

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to={home} replace /> : <Login />} />

      <Route element={<RequireRole role="author"><Layout /></RequireRole>}>
        <Route path="/books" element={<MyBooks />} />
        <Route path="/tickets" element={<MyTickets />} />
        <Route path="/tickets/new" element={<NewTicket />} />
        <Route path="/tickets/:id" element={<AuthorTicket />} />
      </Route>

      <Route element={<RequireRole role="admin"><Layout /></RequireRole>}>
        <Route path="/admin/tickets" element={<Queue />} />
        <Route path="/admin/tickets/:id" element={<AdminTicket />} />
      </Route>

      <Route path="*" element={<Navigate to={home} replace />} />
    </Routes>
  )
}
