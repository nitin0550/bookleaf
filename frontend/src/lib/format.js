export const money = (v) =>
  v === null || v === undefined || v === '' ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

export const date = (v) =>
  v ? new Date(v).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'

export const dateTime = (v) =>
  v ? new Date(v).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—'

export function timeAgo(v) {
  if (!v) return ''
  const s = Math.round((Date.now() - new Date(v).getTime()) / 1000)
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

export function timeUntil(v) {
  if (!v) return ''
  const mins = Math.round((new Date(v).getTime() - Date.now()) / 60000)
  const abs = Math.abs(mins)
  const label = abs < 60 ? `${abs}m` : abs < 48 * 60 ? `${Math.round(abs / 60)}h` : `${Math.round(abs / 1440)}d`
  return mins >= 0 ? `due in ${label}` : `${label} overdue`
}

export const CATEGORY_LABELS = {
  royalty_payments: 'Royalty & Payments',
  isbn_metadata: 'ISBN & Metadata',
  printing_quality: 'Printing & Quality',
  distribution_availability: 'Distribution',
  book_status_production: 'Production Updates',
  general_inquiry: 'General Inquiry',
}

export const STATUS_LABELS = { open: 'Open', in_progress: 'In Progress', resolved: 'Resolved', closed: 'Closed' }
export const PRIORITY_LABELS = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }
export const SOURCE_LABELS = { ai: 'AI', rules: 'Rules', admin: 'Staff' }
