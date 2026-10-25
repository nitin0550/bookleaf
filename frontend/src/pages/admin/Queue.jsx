import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStats, useTickets } from '../../api/hooks'
import { CategoryTag, EmptyState, ErrorBanner, PriorityBadge, Spinner, StatusBadge } from '../../components/ui'
import { CATEGORY_LABELS, PRIORITY_LABELS, timeAgo, timeUntil } from '../../lib/format'

const STATUS_VIEWS = [
  { key: 'open,in_progress', label: 'Active' },
  { key: 'open', label: 'Open' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'closed', label: 'Closed' },
  { key: '', label: 'All' },
]

const DEFAULT_FILTERS = {
  status: 'open,in_progress', category: '', priority: '', assigned: '', q: '',
  created_after: '', created_before: '', overdue: '', ordering: 'urgency', page: 1,
}

function StatsStrip() {
  const { data } = useStats()
  if (!data) return <div className="stats stats-skeleton" />
  const { queue, ai } = data
  const urgent = queue.unresolved_by_priority.critical + queue.unresolved_by_priority.high
  const usage = ai.last_30_days
  return (
    <section className="stats">
      <div className="stat"><span className="stat-label">Active tickets</span>
        <span className="stat-value">{queue.by_status.open + queue.by_status.in_progress}</span>
        <span className="stat-hint">{queue.by_status.open} open · {queue.unassigned} unassigned</span></div>
      <div className={`stat ${urgent ? 'stat-danger' : ''}`}><span className="stat-label">Critical + High</span>
        <span className="stat-value">{urgent}</span>
        <span className="stat-hint">{queue.unresolved_by_priority.critical} critical</span></div>
      <div className={`stat ${queue.overdue ? 'stat-danger' : ''}`}><span className="stat-label">Past first-response SLA</span>
        <span className="stat-value">{queue.overdue}</span>
        <span className="stat-hint">{queue.awaiting_staff} awaiting our reply</span></div>
      <div className="stat"><span className="stat-label">AI assistant</span>
        <span className={`stat-value ${ai.enabled && !ai.circuit_open ? '' : 'warn'}`}>
          {!ai.enabled ? 'Off' : ai.circuit_open ? 'Paused' : 'Healthy'}
        </span>
        <span className="stat-hint">
          {ai.enabled
            ? `${usage.calls} calls · $${usage.estimated_cost_usd.toFixed(3)} / 30d` +
              (ai.category_override_rate !== null ? ` · ${(ai.category_override_rate * 100).toFixed(0)}% re-categorised` : '')
            : 'Rules + templates in use'}
        </span></div>
    </section>
  )
}

export default function Queue() {
  const navigate = useNavigate()
  const [f, setF] = useState(DEFAULT_FILTERS)
  const set = (patch) => setF((prev) => ({ ...prev, page: 1, ...patch }))
  const { data, isLoading, isFetching, error, refetch } = useTickets(f)

  const filtersActive = ['category', 'priority', 'assigned', 'q', 'created_after', 'created_before', 'overdue']
    .some((k) => f[k])

  return (
    <div className="page wide">
      <div className="page-head">
        <div>
          <h1>Ticket Queue</h1>
          <p className="muted">Sorted by urgency: unresolved first, then priority, then oldest.</p>
        </div>
      </div>

      <StatsStrip />

      <div className="segmented">
        {STATUS_VIEWS.map((s) => (
          <button key={s.key} className={f.status === s.key ? 'on' : ''} onClick={() => set({ status: s.key })}>{s.label}</button>
        ))}
      </div>

      <div className="filters">
        <input type="search" placeholder="Search subject, author, book, BL-00012…" value={f.q} onChange={(e) => set({ q: e.target.value })} />
        <select value={f.category} onChange={(e) => set({ category: e.target.value })} aria-label="Category">
          <option value="">All categories</option>
          {Object.entries(CATEGORY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={f.priority} onChange={(e) => set({ priority: e.target.value })} aria-label="Priority">
          <option value="">All priorities</option>
          {Object.entries(PRIORITY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={f.assigned} onChange={(e) => set({ assigned: e.target.value })} aria-label="Assignee">
          <option value="">Anyone</option>
          <option value="me">Assigned to me</option>
          <option value="unassigned">Unassigned</option>
        </select>
        <label className="inline">From <input type="date" value={f.created_after} onChange={(e) => set({ created_after: e.target.value })} /></label>
        <label className="inline">To <input type="date" value={f.created_before} onChange={(e) => set({ created_before: e.target.value })} /></label>
        <label className="inline check">
          <input type="checkbox" checked={f.overdue === 'true'} onChange={(e) => set({ overdue: e.target.checked ? 'true' : '' })} /> Past SLA
        </label>
        <select value={f.ordering} onChange={(e) => set({ ordering: e.target.value })} aria-label="Sort">
          <option value="urgency">Most urgent</option>
          <option value="oldest">Oldest first</option>
          <option value="newest">Newest first</option>
          <option value="updated">Recently updated</option>
        </select>
        {filtersActive && <button className="btn btn-ghost btn-sm" onClick={() => setF({ ...DEFAULT_FILTERS, status: f.status })}>Clear</button>}
      </div>

      {isLoading ? <Spinner /> : error ? <ErrorBanner error={error} onRetry={refetch} /> :
        data.results.length === 0 ? (
          <EmptyState title="Nothing here">{filtersActive ? 'No tickets match these filters.' : 'The queue is clear.'}</EmptyState>
        ) : (
          <>
            <div className={`table-wrap ${isFetching ? 'is-fetching' : ''}`}>
              <table className="queue">
                <thead>
                  <tr>
                    <th>Priority</th><th>Ticket</th><th>Author</th><th>Category</th>
                    <th>Status</th><th>Assignee</th><th>Age / SLA</th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((t) => (
                    <tr key={t.id} className={t.is_overdue ? 'row-overdue' : ''} onClick={() => navigate(`/admin/tickets/${t.id}`)}
                        tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && navigate(`/admin/tickets/${t.id}`)}>
                      <td><PriorityBadge priority={t.priority} source={t.priority_source} /></td>
                      <td className="cell-subject">
                        <span className="ref">{t.reference}</span>
                        {t.awaiting_staff && t.status !== 'closed' && t.status !== 'resolved' && <span className="dot" title="Awaiting our reply" />}
                        <strong>{t.subject}</strong>
                        <span className="muted small">{t.ai_summary || (t.book ? t.book.title : 'General / Account')}</span>
                      </td>
                      <td>{t.author.name}<span className="muted small block">{t.author.author_id}</span></td>
                      <td>
                        <CategoryTag category={t.category} source={t.category_source} />
                        {t.ai_status === 'pending' && <span className="muted small block">AI classifying…</span>}
                      </td>
                      <td><StatusBadge status={t.status} /></td>
                      <td>{t.assigned_to?.full_name ?? <span className="muted">—</span>}</td>
                      <td>
                        {timeAgo(t.created_at)}
                        {t.status !== 'resolved' && t.status !== 'closed' && !t.first_response_at && (
                          <span className={`small block ${t.is_overdue ? 'danger' : 'muted'}`}>{timeUntil(t.sla_due_at)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span className="muted small">{data.count} ticket{data.count === 1 ? '' : 's'}</span>
              <button className="btn btn-ghost btn-sm" disabled={!data.previous} onClick={() => setF((p) => ({ ...p, page: p.page - 1 }))}>← Prev</button>
              <button className="btn btn-ghost btn-sm" disabled={!data.next} onClick={() => setF((p) => ({ ...p, page: p.page + 1 }))}>Next →</button>
            </div>
          </>
        )}
    </div>
  )
}
