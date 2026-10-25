import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTickets } from '../../api/hooks'
import { EmptyState, ErrorBanner, Spinner, StatusBadge } from '../../components/ui'
import { timeAgo } from '../../lib/format'

const FILTERS = [
  { key: '', label: 'All' },
  { key: 'open,in_progress', label: 'Active' },
  { key: 'resolved,closed', label: 'Resolved' },
]

export default function MyTickets() {
  const [status, setStatus] = useState('')
  const { data, isLoading, error, refetch } = useTickets({ status, ordering: 'updated' })

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>My Tickets</h1>
          <p className="muted">Replies from the BookLeaf team appear here automatically.</p>
        </div>
        <Link className="btn btn-primary" to="/tickets/new">New query</Link>
      </div>

      <div className="segmented">
        {FILTERS.map((f) => (
          <button key={f.key} className={status === f.key ? 'on' : ''} onClick={() => setStatus(f.key)}>{f.label}</button>
        ))}
      </div>

      {isLoading ? <Spinner /> : error ? <ErrorBanner error={error} onRetry={refetch} /> :
        data.results.length === 0 ? (
          <EmptyState title="No tickets here" action={<Link className="btn btn-primary" to="/tickets/new">Raise a query</Link>}>
            Questions about royalties, ISBNs, printing or your book's status? We're here to help.
          </EmptyState>
        ) : (
          <ul className="ticket-list">
            {data.results.map((t) => (
              <li key={t.id}>
                <Link to={`/tickets/${t.id}`} className="ticket-row">
                  <div className="ticket-main">
                    <span className="ref">{t.reference}</span>
                    <strong>{t.subject}</strong>
                    <span className="muted small">{t.book ? t.book.title : 'General / Account'} · {t.category_label}</span>
                  </div>
                  <div className="ticket-meta">
                    {t.last_reply_from === 'admin' && t.status !== 'closed' && <span className="tag tag-new">Reply from BookLeaf</span>}
                    <StatusBadge status={t.status} />
                    <span className="muted small">updated {timeAgo(t.updated_at)}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
    </div>
  )
}
