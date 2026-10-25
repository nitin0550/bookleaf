import { Link } from 'react-router-dom'
import { useBooks } from '../../api/hooks'
import { EmptyState, ErrorBanner, Spinner } from '../../components/ui'
import { date, money } from '../../lib/format'

function Stat({ label, value, hint, tone }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  )
}

function ProductionTracker({ progress }) {
  return (
    <div className="tracker">
      <p className="tracker-label">
        In production · <strong>{progress.stage}</strong> (step {progress.step} of {progress.total_steps})
      </p>
      <ol className="tracker-steps">
        {progress.stages.map((s, i) => (
          <li key={s} className={i + 1 < progress.step ? 'done' : i + 1 === progress.step ? 'current' : ''} title={s}>
            <span className="sr-only">{s}</span>
          </li>
        ))}
      </ol>
      <p className="muted small">
        Sales and royalties will appear here once your book is Published &amp; Live. We email you at every stage.
      </p>
    </div>
  )
}

function BookCard({ book }) {
  const flags = book.royalty_flags
  return (
    <article className="card book">
      <header className="book-head">
        <div>
          <h3>{book.title}</h3>
          <p className="muted small">
            {book.genre} · ISBN <code>{book.isbn || 'pending'}</code>
          </p>
        </div>
        <span className={`badge ${book.is_published ? 'status-resolved' : 'status-in_progress'}`}>
          {book.is_published ? 'Published & Live' : 'In Production'}
        </span>
      </header>

      {book.is_published ? (
        <>
          <dl className="book-grid">
            <div><dt>Published</dt><dd>{date(book.publication_date)}</dd></div>
            <div><dt>MRP</dt><dd>{money(book.mrp)}</dd></div>
            <div><dt>Copies sold</dt><dd>{book.total_copies_sold.toLocaleString('en-IN')}</dd></div>
            <div><dt>Royalty / copy</dt><dd>{money(book.author_royalty_per_copy)}</dd></div>
            <div><dt>Royalty earned</dt><dd>{money(book.total_royalty_earned)}</dd></div>
            <div><dt>Royalty paid</dt><dd>{money(book.royalty_paid)}</dd></div>
            <div><dt>Royalty pending</dt><dd className={Number(book.royalty_pending) > 0 ? 'pending' : ''}>{money(book.royalty_pending)}</dd></div>
            <div><dt>Last payout</dt><dd>{book.last_royalty_payout_date ? date(book.last_royalty_payout_date) : 'Not yet'}</dd></div>
          </dl>
          {book.available_on.length > 0 && (
            <p className="platforms">{book.available_on.map((p) => <span key={p} className="tag">{p}</span>)}</p>
          )}
          {flags.below_payout_threshold && (
            <p className="note">Pending royalty is below the ₹1,000 payout minimum on its own; it rolls over to the next quarter unless your account total crosses the threshold.</p>
          )}
        </>
      ) : (
        <ProductionTracker progress={book.production_progress} />
      )}

      <footer className="book-foot">
        <Link className="btn btn-ghost btn-sm" to={`/tickets/new?book=${book.book_id}`}>Ask about this book</Link>
      </footer>
    </article>
  )
}

export default function MyBooks() {
  const { data, isLoading, error, refetch } = useBooks()
  if (isLoading) return <Spinner />
  if (error) return <ErrorBanner error={error} onRetry={refetch} />

  const { results: books, summary } = data
  const s = summary?.schedule

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>My Books</h1>
          <p className="muted">Royalties are calculated quarterly and paid within 45 days of the quarter ending.</p>
        </div>
        <Link className="btn btn-primary" to="/tickets/new">Raise a query</Link>
      </div>

      {summary && (
        <section className="stats">
          <Stat label="Total royalty earned" value={money(summary.total_earned)} />
          <Stat label="Paid to you" value={money(summary.total_paid)} />
          <Stat label="Pending" value={money(summary.total_pending)} tone={summary.total_pending > 0 ? 'accent' : undefined}
                hint={summary.total_pending > 0 && !summary.meets_payout_threshold ? 'Below ₹1,000 minimum, rolls over' : undefined} />
          <Stat label="Next payout date" value={date(s.next_payout_date)} hint={`For ${s.next_payout_covers} sales`} />
        </section>
      )}

      {books.length === 0 ? (
        <EmptyState title="No books yet">Once your manuscript is received, your book will appear here.</EmptyState>
      ) : (
        <div className="book-list">{books.map((b) => <BookCard key={b.book_id} book={b} />)}</div>
      )}
    </div>
  )
}
