// Minimal fetch wrapper around the BookLeaf REST API.
// - Adds the auth token
// - Normalises every error into ApiError using the backend's uniform error envelope
// - Logs the user out on 401 so a revoked/expired token never leaves the UI stuck

const TOKEN_KEY = 'bookleaf.token'

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export const tokenStore = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (t) => {
    try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
  },
}

let onUnauthorized = () => {}
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn }

export async function api(path, { method = 'GET', body, query, form } = {}) {
  const url = new URL(`/api${path}`, window.location.origin)
  if (query) {
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    })
  }

  const headers = { Accept: 'application/json' }
  const token = tokenStore.get()
  if (token) headers.Authorization = `Token ${token}`

  let payload
  if (form) {
    payload = form // FormData: browser sets multipart boundary
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(url, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection and try again.')
  }

  if (res.status === 204) return null
  const data = await res.json().catch(() => null)

  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized()
    const err = data?.error
    throw new ApiError(res.status, err?.code ?? 'error', err?.message ?? `Request failed (${res.status})`, err?.details)
  }
  return data
}

/** Open a protected file (e.g. a ticket attachment) in a new tab using the auth token. */
export async function openProtectedFile(path) {
  const win = window.open('', '_blank') // open synchronously so popup blockers allow it
  const res = await fetch(path, { headers: { Authorization: `Token ${tokenStore.get()}` } })
  if (!res.ok) { win?.close(); throw new ApiError(res.status, 'download_failed', 'Could not open the attachment.') }
  const url = URL.createObjectURL(await res.blob())
  if (win) win.location.href = url
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
