import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  useAddNote, useAIDraft, useAssignToMe, usePostMessage, useReclassify, useRegenerateDraft,
  useStaff, useTicket, useUpdateTicket,
} from '../../api/hooks'
import { useAuth } from '../../auth/AuthContext'
import { AttachmentLink, CategoryTag, ErrorBanner, PriorityBadge, Spinner, StatusBadge, Thread } from '../../components/ui'
import {
  CATEGORY_LABELS, PRIORITY_LABELS, SOURCE_LABELS, STATUS_LABELS, date, dateTime, money, timeAgo, timeUntil,
} from '../../lib/format'

/* ---------------------------------------------------------------- triage */
function TriagePanel({ t }) {
  const update = useUpdateTicket(t.id)
  const reclassify = useReclassify(t.id)
  const aiDisagrees = t.ai_status === 'completed' &&
    ((t.category_source === 'admin' && t.ai_category !== t.category) ||
     (t.priority_source === 'admin' && t.ai_priority !== t.priority))

  return (
    <section className="card triage">
      <div className="triage-grid">
        <label>
          <span>Category <span className="src">set by {SOURCE_LABELS[t.category_source]}</span></span>
          <select value={t.category} onChange={(e) => update.mutate({ category: e.target.value })}>
            {Object.entries(CATEGORY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>
          <span>Priority <span className="src">set by {SOURCE_LABELS[t.priority_source]}</span></span>
          <select value={t.priority} onChange={(e) => update.mutate({ priority: e.target.value })}>
            {Object.entries(PRIORITY_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </div>
      <div className="ai-line">
        {t.ai_status === 'completed' && (
          <p>
            <span className="tag tag-ai">AI</span>{' '}
            {CATEGORY_LABELS[t.ai_category]} · {PRIORITY_LABELS[t.ai_priority]}
            {t.ai_confidence !== null && <span className="muted"> · {(t.ai_confidence * 100).toFixed(0)}% confident</span>}
            {t.ai_rationale && <span className="muted"> — {t.ai_rationale}</span>}
            {aiDisagrees && <span className="muted"> (overridden by staff)</span>}
          </p>
        )}
        {t.ai_status === 'pending' && <p className="muted">AI is classifying this ticket…</p>}
        {(t.ai_status === 'failed' || t.ai_status === 'disabled') && (
          <p className="warn-text">
            AI classification unavailable — values came from keyword rules. Please double-check.
          </p>
        )}
        {t.ai_status !== 'pending' && (
          <button className="btn btn-ghost btn-sm" onClick={() => reclassify.mutate()} disabled={reclassify.isPending}>
            {reclassify.isPending ? 'Re-running…' : 'Re-run AI triage'}
          </button>
        )}
      </div>
      <ErrorBanner error={update.error || reclassify.error} />
    </section>
  )
}

/* ---------------------------------------------------------------- reply */
function ReplyComposer({ t }) {
  const closed = t.status === 'closed'
  // Only draft when the author is waiting on us (saves tokens; a draft replying to our
  // own last message is useless). Staff can still ask for one explicitly.
  const [wantDraft, setWantDraft] = useState(false)
  const draft = useAIDraft(t.id, !closed && (t.awaiting_staff || wantDraft))
  const regenerate = useRegenerateDraft(t.id)
  const send = usePostMessage(t.id)

  const [text, setText] = useState('')
  const [fromDraft, setFromDraft] = useState(false)
  const [nextStatus, setNextStatus] = useState('in_progress')
  const touched = useRef(false)
  const draftBody = draft.data?.body

  // Prefill the editor with the draft, but never clobber what the agent has typed.
  useEffect(() => {
    if (draftBody && !touched.current) {
      setText(draftBody)
      setFromDraft(true)
      if (draft.data.suggested_status) setNextStatus(draft.data.suggested_status)
    }
  }, [draftBody, draft.data?.suggested_status])

  if (closed) return <p className="muted">This ticket is closed. Reopen it from the sidebar to reply.</p>

  function resetToDraft() {
    setText(draft.data.body)
    setFromDraft(true)
    touched.current = false
  }

  function submit(e) {
    e.preventDefault()
    send.mutate({ body: text, ai_assisted: fromDraft, status: nextStatus }, {
      onSuccess: () => { setText(''); setFromDraft(false); setWantDraft(false); touched.current = false },
    })
  }

  const d = draft.data
  const hasPlaceholders = /\[[^\]]{3,}\]/.test(text)

  return (
    <section className="card composer">
      <div className="composer-head">
        <h3>Reply to author</h3>
        <div className="draft-meta">
          {draft.isFetching && !d && <span className="muted small">Drafting reply…</span>}
          {!d && !draft.isFetching && !t.awaiting_staff && (
            <>
              <span className="muted small">Waiting on the author.</span>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setWantDraft(true)}>Draft with AI</button>
            </>
          )}
          {d && (
            <>
              <span className={`tag ${d.source === 'ai' ? 'tag-ai' : 'tag-warn'}`}>
                {d.source === 'ai' ? 'AI draft' : 'Template (AI unavailable)'}
              </span>
              {d.source === 'ai' && (
                <span className="muted small" title={`KB sections: ${d.kb_sections.join(', ')}`}>
                  {d.cached ? 'cached' : `${d.input_tokens + d.output_tokens} tokens`}
                </span>
              )}
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => regenerate.mutate()} disabled={regenerate.isPending}>
                {regenerate.isPending ? 'Regenerating…' : 'Regenerate'}
              </button>
              {text !== d.body && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={resetToDraft}>Reset to draft</button>
              )}
            </>
          )}
        </div>
      </div>

      {d?.agent_notes && <p className="agent-note"><strong>For you:</strong> {d.agent_notes}</p>}
      {draft.error && <p className="warn-text small">Couldn’t load a draft ({draft.error.message}). You can write the reply manually.</p>}

      <form className="form" onSubmit={submit}>
        <textarea rows={12} value={text} placeholder="Write your reply…"
                  onChange={(e) => { touched.current = true; setText(e.target.value) }} />
        {hasPlaceholders && <p className="warn-text small">Fill in the [bracketed] placeholders before sending.</p>}
        <ErrorBanner error={send.error} />
        <div className="form-actions">
          <label className="inline">
            After sending, set status
            <select value={nextStatus} onChange={(e) => setNextStatus(e.target.value)}>
              <option value="in_progress">In Progress</option>
              <option value="resolved">Resolved</option>
              <option value="closed">Closed</option>
            </select>
          </label>
          <button className="btn btn-primary" disabled={send.isPending || text.trim().length < 2 || hasPlaceholders}>
            {send.isPending ? 'Sending…' : 'Send to author'}
          </button>
        </div>
      </form>
    </section>
  )
}

/* ---------------------------------------------------------------- notes */
function InternalNotes({ t }) {
  const add = useAddNote(t.id)
  const [body, setBody] = useState('')
  return (
    <section className="card notes">
      <h3>Internal notes <span className="muted small">— staff only, never shown to the author</span></h3>
      {t.internal_notes.length === 0 ? <p className="muted small">No notes yet.</p> : (
        <ul className="note-list">
          {t.internal_notes.map((n) => (
            <li key={n.id}><div className="msg-head"><strong>{n.created_by.full_name}</strong><time>{timeAgo(n.created_at)}</time></div>{n.body}</li>
          ))}
        </ul>
      )}
      <form className="note-form" onSubmit={(e) => { e.preventDefault(); add.mutate(body, { onSuccess: () => setBody('') }) }}>
        <input value={body} onChange={(e) => setBody(e.target.value)} placeholder="Add a note for the team…" />
        <button className="btn btn-ghost btn-sm" disabled={add.isPending || body.trim().length < 2}>Add note</button>
      </form>
      <ErrorBanner error={add.error} />
    </section>
  )
}

/* ---------------------------------------------------------------- sidebar */
function Sidebar({ t }) {
  const { user } = useAuth()
  const staff = useStaff()
  const update = useUpdateTicket(t.id)
  const assignMe = useAssignToMe(t.id)
  const a = t.author_context
  const focusBook = a.books.find((b) => b.book_id === t.book?.book_id)

  return (
    <aside className="sidebar">
      <section className="card">
        <h4>Ticket</h4>
        <label className="side-field">Status
          <select value={t.status} onChange={(e) => update.mutate({ status: e.target.value })}>
            {Object.entries(STATUS_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="side-field">Assignee
          <select value={t.assigned_to?.id ?? ''} onChange={(e) => update.mutate({ assigned_to: e.target.value ? Number(e.target.value) : null })}>
            <option value="">Unassigned</option>
            {staff.data?.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
          </select>
        </label>
        {t.assigned_to?.id !== user.id && (
          <button className="btn btn-ghost btn-sm btn-block" onClick={() => assignMe.mutate()} disabled={assignMe.isPending}>Assign to me</button>
        )}
        <dl className="kv">
          <dt>Opened</dt><dd>{dateTime(t.created_at)}</dd>
          <dt>First response</dt>
          <dd className={t.is_overdue ? 'danger' : ''}>{t.first_response_at ? dateTime(t.first_response_at) : timeUntil(t.sla_due_at)}</dd>
        </dl>
        <ErrorBanner error={update.error || assignMe.error} />
      </section>

      <section className="card">
        <h4>{a.name} <span className="muted small">{a.author_id}</span></h4>
        <p className="muted small">{a.email} · {a.phone} · {a.city}<br />Author since {date(a.joined_date)}</p>
        <dl className="kv">
          <dt>Earned</dt><dd>{money(a.royalty_summary.total_earned)}</dd>
          <dt>Paid</dt><dd>{money(a.royalty_summary.total_paid)}</dd>
          <dt>Pending</dt><dd>{money(a.royalty_summary.total_pending)}</dd>
          <dt>Next payout</dt><dd>{date(a.royalty_summary.schedule.next_payout_date)}</dd>
          <dt>Bank linked</dt><dd>{a.bank_account_linked ? 'Yes' : <span className="danger">No</span>}</dd>
        </dl>
      </section>

      {focusBook && (
        <section className="card">
          <h4>{focusBook.title}</h4>
          <p className="muted small"><code>{focusBook.isbn}</code> · {focusBook.status}</p>
          {focusBook.is_published ? (
            <dl className="kv">
              <dt>Published</dt><dd>{date(focusBook.publication_date)}</dd>
              <dt>MRP</dt><dd>{money(focusBook.mrp)}</dd>
              <dt>Sold</dt><dd>{focusBook.total_copies_sold}</dd>
              <dt>Pending</dt><dd>{money(focusBook.royalty_pending)}</dd>
              <dt>Last payout</dt><dd>{focusBook.last_royalty_payout_date ? date(focusBook.last_royalty_payout_date) : 'Never'}</dd>
              <dt>Printer</dt><dd>{focusBook.print_partner}</dd>
              <dt>Listed on</dt><dd>{focusBook.available_on.join(', ')}</dd>
            </dl>
          ) : <p className="small">Stage {focusBook.production_progress.step}/{focusBook.production_progress.total_steps}: {focusBook.production_progress.stage}</p>}
          {focusBook.royalty_flags.possibly_overdue && <p className="flag">Pending royalty is past a payout deadline — check for a missed payout.</p>}
          {focusBook.royalty_flags.never_paid && <p className="flag">No royalty has ever been paid on this title.</p>}
        </section>
      )}

      <section className="card">
        <h4>Other books</h4>
        <ul className="mini-books">
          {a.books.filter((b) => b.book_id !== focusBook?.book_id).map((b) => (
            <li key={b.book_id}><span>{b.title}</span><span className="muted small">{b.is_published ? `${money(b.royalty_pending)} pending` : b.production_progress.stage}</span></li>
          ))}
          {a.books.length <= (focusBook ? 1 : 0) && <li className="muted small">None</li>}
        </ul>
      </section>

      <section className="card">
        <h4>Activity</h4>
        <ol className="timeline">
          {t.events.map((e) => (
            <li key={e.id}><span>{describeEvent(e)}</span><time className="muted small">{timeAgo(e.created_at)} · {e.actor}</time></li>
          ))}
        </ol>
      </section>
    </aside>
  )
}

function describeEvent(e) {
  switch (e.kind) {
    case 'created': return 'Ticket created'
    case 'status_changed': return `Status: ${STATUS_LABELS[e.from_value]} → ${STATUS_LABELS[e.to_value]}`
    case 'category_changed': return `Category: ${e.from_value} → ${e.to_value}`
    case 'priority_changed': return `Priority: ${e.from_value} → ${e.to_value}`
    case 'assigned': return e.to_value === 'Unassigned' ? 'Unassigned' : `Assigned to ${e.to_value}`
    case 'ai_classified': return `AI triage: ${e.to_value}`
    case 'ai_failed': return 'AI triage failed — rules used'
    case 'replied': return e.to_value === 'staff' ? 'Staff replied' : 'Author replied'
    default: return e.kind
  }
}

/* ---------------------------------------------------------------- page */
export default function AdminTicket() {
  const { id } = useParams()
  const { data: t, isLoading, error, refetch } = useTicket(id)

  if (isLoading) return <Spinner />
  if (error) return <ErrorBanner error={error.status === 404 ? { message: 'Ticket not found.' } : error} onRetry={refetch} />

  return (
    <div className="page wide">
      <Link to="/admin/tickets" className="back">← Queue</Link>
      <div className="page-head">
        <div>
          <p className="ref">{t.reference} · {t.book ? t.book.title : 'General / Account level'}</p>
          <h1>{t.subject}</h1>
          <div className="head-badges">
            <StatusBadge status={t.status} />
            <PriorityBadge priority={t.priority} source={t.priority_source} />
            <CategoryTag category={t.category} source={t.category_source} />
            {t.is_overdue && <span className="badge prio-critical">Past SLA</span>}
          </div>
        </div>
      </div>

      <div className="workspace">
        <div className="workspace-main">
          <TriagePanel t={t} />
          <AttachmentLink url={t.attachment_url} label="View author’s attachment" />
          <Thread ticket={t} viewer="admin" />
          <ReplyComposer key={t.id} t={t} />
          <InternalNotes t={t} />
        </div>
        <Sidebar t={t} />
      </div>
    </div>
  )
}
