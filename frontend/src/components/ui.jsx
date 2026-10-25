import { openProtectedFile } from '../api/client'
import { CATEGORY_LABELS, PRIORITY_LABELS, SOURCE_LABELS, STATUS_LABELS, dateTime, timeAgo } from '../lib/format'

export const StatusBadge = ({ status }) => (
  <span className={`badge status-${status}`}>{STATUS_LABELS[status] ?? status}</span>
)

export const PriorityBadge = ({ priority, source }) => (
  <span className={`badge prio-${priority}`} title={source ? `Set by: ${SOURCE_LABELS[source]}` : undefined}>
    {PRIORITY_LABELS[priority] ?? priority}
    {source && source !== 'admin' && <span className="badge-src">{SOURCE_LABELS[source]}</span>}
  </span>
)

export const CategoryTag = ({ category, source }) => (
  <span className="tag" title={source ? `Set by: ${SOURCE_LABELS[source]}` : undefined}>
    {CATEGORY_LABELS[category] ?? category}
    {source && source !== 'admin' && <span className="badge-src">{SOURCE_LABELS[source]}</span>}
  </span>
)

export const Spinner = ({ label = 'Loading…' }) => (
  <div className="spinner" role="status"><span className="spinner-dot" />{label}</div>
)

export const ErrorBanner = ({ error, onRetry }) =>
  error ? (
    <div className="alert alert-error" role="alert">
      <span>{error.message ?? String(error)}</span>
      {onRetry && <button className="btn btn-ghost btn-sm" onClick={onRetry}>Try again</button>}
    </div>
  ) : null

export const EmptyState = ({ title, children, action }) => (
  <div className="empty">
    <h3>{title}</h3>
    {children && <p>{children}</p>}
    {action}
  </div>
)

export function FieldError({ error, field }) {
  const msg = error?.details?.[field]
  return msg ? <p className="field-error">{Array.isArray(msg) ? msg.join(' ') : String(msg)}</p> : null
}

/** Conversation thread shared by both portals. */
export function Thread({ ticket, viewer }) {
  const items = [
    { id: 'original', sender_role: 'author', sender_name: viewer === 'author' ? 'You' : ticket.author?.name,
      body: ticket.description, created_at: ticket.created_at },
    ...ticket.messages,
  ]
  return (
    <ol className="thread">
      {items.map((m) => {
        const mine = (viewer === 'author') === (m.sender_role === 'author')
        return (
          <li key={m.id} className={`msg ${m.sender_role === 'admin' ? 'msg-staff' : 'msg-author'} ${mine ? 'msg-mine' : ''}`}>
            <div className="msg-head">
              <strong>{viewer === 'author' && m.sender_role === 'author' ? 'You' : m.sender_name}</strong>
              {m.ai_assisted && <span className="tag tag-ai" title="Started from an AI draft, reviewed by staff">AI-assisted</span>}
              <time title={dateTime(m.created_at)}>{timeAgo(m.created_at)}</time>
            </div>
            <div className="msg-body">{m.body}</div>
          </li>
        )
      })}
    </ol>
  )
}

export const AttachmentLink = ({ url, label = 'View attachment' }) =>
  url ? (
    <p><button type="button" className="btn btn-ghost btn-sm" onClick={() => openProtectedFile(url).catch(() => {})}>{label}</button></p>
  ) : null
