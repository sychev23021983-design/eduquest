import { createContext, useContext, useState } from 'react'

const Ctx = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(localStorage.getItem('eq_token') || '')
  const [role,  setRole]  = useState(localStorage.getItem('eq_role')  || '')

  const login = (t, r) => {
    setToken(t); setRole(r)
    localStorage.setItem('eq_token', t)
    localStorage.setItem('eq_role',  r)
  }
  const logout = () => {
    setToken(''); setRole('')
    localStorage.removeItem('eq_token')
    localStorage.removeItem('eq_role')
  }

  return <Ctx.Provider value={{ token, role, login, logout }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)
