import { useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { usePostMessage, useTicket } from '../../api/hooks'
import { AttachmentLink, ErrorBanner, Spinner, StatusBadge, Thread } from '../../components/ui'
import { dateTime } from '../../lib/format'

const STATUS_HELP = {
  open: 'Our team has received your query and will reply soon.',
  in_progress: 'A BookLeaf team member is working on this.',
  resolved: 'Marked resolved. Reply below if anything is still not right — it will reopen the ticket.',
  closed: 'This ticket is closed. Please raise a new query if you need more help.',
}

export default function AuthorTicket() {
  const { id } = useParams()
  const location = useLocation()
  const { data: t, isLoading, error, refetch } = useTicket(id)
  const reply = usePostMessage(id)
  const [body, setBody] = useState('')

  if (isLoading) return <Spinner />
  if (error) return <ErrorBanner error={error.status === 404 ? { message: 'Ticket not found.' } : error} onRetry={refetch} />

  function send(e) {
    e.preventDefault()
    reply.mutate({ body }, { onSuccess: () => setBody('') })
  }

  return (
    <div className="page narrow">
      <Link to="/tickets" className="back">← My Tickets</Link>
      {location.state?.justCreated && (
        <div className="alert alert-success">Thanks — your query {t.reference} has been received. You'll see our reply here.</div>
      )}
      <div className="page-head">
        <div>
          <p className="ref">{t.reference} · {t.category_label}</p>
          <h1>{t.subject}</h1>
          <p className="muted small">
            {t.book ? t.book.title : 'General / Account level'} · opened {dateTime(t.created_at)}
          </p>
        </div>
        <StatusBadge status={t.status} />
      </div>
      <p className="status-help">{STATUS_HELP[t.status]}</p>

      <AttachmentLink url={t.attachment_url} />

      <Thread ticket={t} viewer="author" />

      {t.status !== 'closed' && (
        <form className="card form reply" onSubmit={send}>
          <label>
            Add a reply
            <textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Add more details or reply to the team…" required minLength={2} />
          </label>
          <ErrorBanner error={reply.error} />
          <div className="form-actions">
            <button className="btn btn-primary" disabled={reply.isPending || body.trim().length < 2}>
              {reply.isPending ? 'Sending…' : 'Send reply'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
