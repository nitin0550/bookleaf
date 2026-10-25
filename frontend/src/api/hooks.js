// React Query hooks: one place that knows endpoint paths and cache keys.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export const useBooks = () => useQuery({ queryKey: ['books'], queryFn: () => api('/books/') })

export const useTickets = (filters = {}) =>
  useQuery({
    queryKey: ['tickets', filters],
    queryFn: () => api('/tickets/', { query: filters }),
    placeholderData: (prev) => prev, // keep the table steady while filters change
  })

export const useTicket = (id) =>
  useQuery({ queryKey: ['ticket', String(id)], queryFn: () => api(`/tickets/${id}/`) })

export const useStats = () => useQuery({ queryKey: ['stats'], queryFn: () => api('/admin/stats/') })

export const useStaff = () =>
  useQuery({ queryKey: ['staff'], queryFn: () => api('/staff/'), staleTime: 5 * 60_000 })

export const useAIDraft = (id, enabled) =>
  useQuery({
    queryKey: ['ai-draft', String(id)],
    queryFn: () => api(`/tickets/${id}/ai-draft/`),
    enabled,
    staleTime: Infinity, // the server caches drafts; we only refetch on explicit regenerate
    retry: false,
  })

function useTicketMutation(id, fn, { dropDraft = false } = {}) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      // A sent reply makes the current draft obsolete.
      if (dropDraft) qc.removeQueries({ queryKey: ['ai-draft', String(id)] })
      if (data?.id && data?.reference) qc.setQueryData(['ticket', String(id)], data)
      qc.invalidateQueries({ queryKey: ['ticket', String(id)] })
      qc.invalidateQueries({ queryKey: ['tickets'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
  })
}

export const useCreateTicket = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (form) => api('/tickets/', { method: 'POST', form }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tickets'] }),
  })
}

export const usePostMessage = (id) =>
  useTicketMutation(id, (body) => api(`/tickets/${id}/messages/`, { method: 'POST', body }), { dropDraft: true })

export const useUpdateTicket = (id) =>
  useTicketMutation(id, (body) => api(`/tickets/${id}/`, { method: 'PATCH', body }))

export const useAssignToMe = (id) =>
  useTicketMutation(id, () => api(`/tickets/${id}/assign-to-me/`, { method: 'POST' }))

export const useAddNote = (id) =>
  useTicketMutation(id, (body) => api(`/tickets/${id}/notes/`, { method: 'POST', body: { body } }))

export const useReclassify = (id) =>
  useTicketMutation(id, () => api(`/tickets/${id}/reclassify/`, { method: 'POST' }))

export const useRegenerateDraft = (id) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api(`/tickets/${id}/ai-draft/`, { method: 'POST' }),
    onSuccess: (data) => qc.setQueryData(['ai-draft', String(id)], data),
  })
}
