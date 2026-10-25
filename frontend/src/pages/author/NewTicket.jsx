import { useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useBooks, useCreateTicket } from '../../api/hooks'
import { ErrorBanner, FieldError, Spinner } from '../../components/ui'

const MAX_MB = 5
const ACCEPT = '.png,.jpg,.jpeg,.webp,.pdf'

export default function NewTicket() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const books = useBooks()
  const create = useCreateTicket()
  const fileRef = useRef(null)

  const [bookId, setBookId] = useState(params.get('book') ?? '')
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [file, setFile] = useState(null)
  const [fileError, setFileError] = useState(null)

  function pickFile(e) {
    const f = e.target.files?.[0] ?? null
    setFileError(null)
    if (f && f.size > MAX_MB * 1024 * 1024) {
      setFileError(`File is larger than ${MAX_MB} MB.`)
      e.target.value = ''
      return setFile(null)
    }
    setFile(f)
  }

  function submit(e) {
    e.preventDefault()
    const form = new FormData()
    if (bookId) form.append('book_id', bookId)
    form.append('subject', subject)
    form.append('description', description)
    if (file) form.append('attachment', file)
    create.mutate(form, { onSuccess: (t) => navigate(`/tickets/${t.id}`, { state: { justCreated: true } }) })
  }

  if (books.isLoading) return <Spinner />
  const selected = books.data?.results.find((b) => b.book_id === bookId)

  return (
    <div className="page narrow">
      <h1>Raise a support query</h1>
      <p className="muted">Our team usually replies within one business day. Urgent royalty and ISBN issues are prioritised.</p>

      <form className="card form" onSubmit={submit}>
        <label>
          Which book is this about?
          <select value={bookId} onChange={(e) => setBookId(e.target.value)}>
            <option value="">General / Account level</option>
            {books.data?.results.map((b) => (
              <option key={b.book_id} value={b.book_id}>
                {b.title} {b.is_published ? '' : '(in production)'}
              </option>
            ))}
          </select>
          <FieldError error={create.error} field="book_id" />
        </label>
        {selected && (
          <p className="hint">
            {selected.is_published
              ? `${selected.title}: ${selected.total_copies_sold} copies sold · status ${selected.status}`
              : `${selected.title} is currently at the ${selected.production_progress.stage} stage.`}
          </p>
        )}

        <label>
          Subject
          <input value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)}
                 placeholder="e.g. Royalty for last quarter not received" required minLength={5} />
          <FieldError error={create.error} field="subject" />
        </label>

        <label>
          Describe the issue
          <textarea rows={7} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)}
                    placeholder="Include anything that helps: dates, platform (Amazon, Flipkart…), order numbers, what you expected to see."
                    required minLength={20} />
          <span className="counter">{description.length}/5000</span>
          <FieldError error={create.error} field="description" />
        </label>

        <label>
          Attachment <span className="muted">(optional · photos of print defects, screenshots — PNG, JPG, PDF up to {MAX_MB} MB)</span>
          <input ref={fileRef} type="file" accept={ACCEPT} onChange={pickFile} />
          {fileError && <p className="field-error">{fileError}</p>}
          <FieldError error={create.error} field="attachment" />
        </label>

        {create.error && !create.error.details && <ErrorBanner error={create.error} />}
        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>Cancel</button>
          <button className="btn btn-primary" disabled={create.isPending}>
            {create.isPending ? 'Submitting…' : 'Submit query'}
          </button>
        </div>
      </form>
    </div>
  )
}
