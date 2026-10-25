import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

const INTERVAL_MS = 4000

/**
 * Near-real-time updates via a cheap change feed.
 *
 * Every few seconds we ask `/tickets/changes/?since=<server_time>` which returns only
 * the ids of tickets that changed. Only when something changed do we invalidate the
 * cached ticket queries, so idle polling costs one tiny request and no re-renders.
 * Polling pauses while the tab is hidden and resumes (with an immediate check) on focus.
 *
 * Why polling over WebSockets: it works on any host (including free tiers and
 * serverless), needs no extra infrastructure (Redis/Channels), and a 4s delay feels
 * live for support tickets. The `changes` endpoint is the swap-point for SSE later.
 */
export function useLiveUpdates(enabled = true) {
  const queryClient = useQueryClient()
  const since = useRef(null)
  const [lastChangeAt, setLastChangeAt] = useState(null)
  const [connected, setConnected] = useState(true)

  useEffect(() => {
    if (!enabled) return
    let timer
    let cancelled = false

    const tick = async () => {
      if (document.hidden) return schedule()
      try {
        const res = await api('/tickets/changes/', { query: { since: since.current } })
        if (cancelled) return
        setConnected(true)
        if (since.current && res.changed.length) {
          queryClient.invalidateQueries({ queryKey: ['tickets'] })
          queryClient.invalidateQueries({ queryKey: ['stats'] })
          res.changed.forEach(({ id }) => {
            queryClient.invalidateQueries({ queryKey: ['ticket', String(id)] })
            // Server-side draft cache decides whether a new draft is actually needed.
            queryClient.invalidateQueries({ queryKey: ['ai-draft', String(id)] })
          })
          setLastChangeAt(new Date())
        }
        since.current = res.server_time
      } catch {
        if (!cancelled) setConnected(false)
      }
      schedule()
    }
    const schedule = () => { if (!cancelled) timer = setTimeout(tick, INTERVAL_MS) }
    const onVisible = () => { if (!document.hidden) { clearTimeout(timer); tick() } }

    tick()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [enabled, queryClient])

  return { lastChangeAt, connected }
}
