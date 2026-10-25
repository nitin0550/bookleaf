import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, setUnauthorizedHandler, tokenStore } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(tokenStore.get()))

  const clear = useCallback(() => {
    tokenStore.set(null)
    setUser(null)
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    setUnauthorizedHandler(clear)
    if (!tokenStore.get()) return
    api('/auth/me/')
      .then(setUser)
      .catch(clear)
      .finally(() => setLoading(false))
  }, [clear])

  const login = useCallback(async (email, password) => {
    const { token, user } = await api('/auth/login/', { method: 'POST', body: { email, password } })
    tokenStore.set(token)
    setUser(user)
    return user
  }, [])

  const logout = useCallback(async () => {
    try { await api('/auth/logout/', { method: 'POST' }) } catch { /* token may already be gone */ }
    clear()
  }, [clear])

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
