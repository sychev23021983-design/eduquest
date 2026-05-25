import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [role, setRole] = useState('child')
  const [pass, setPass] = useState('')
  const [err,  setErr]  = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setErr(''); setLoading(true)
    try {
      const res = await api.login({ password: pass, role })
      login(res.token, res.role)
      nav(res.role === 'parent' ? '/parent' : '/')
    } catch (e) { setErr('Неверный пароль') }
    finally { setLoading(false) }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div className="card" style={{ width: 360, padding: 32 }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>🎓</div>
          <h1 style={{ fontSize: 24, fontWeight: 700 }}>EduQuest</h1>
          <p style={{ color: 'var(--muted)', fontSize: 14, marginTop: 4 }}>Образование через игру</p>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {['child', 'parent'].map(r => (
            <button key={r} onClick={() => setRole(r)}
              style={{ flex: 1, padding: '9px 0', borderRadius: 8, border: '1px solid',
                       borderColor: role === r ? 'var(--blue)' : 'var(--border)',
                       background: role === r ? 'var(--blue-light)' : '#fff',
                       color: role === r ? 'var(--blue)' : 'var(--muted)',
                       fontWeight: 500, fontSize: 14 }}>
              {r === 'child' ? '🎮 Я — Артём' : '👨‍💼 Родитель'}
            </button>
          ))}
        </div>

        <form onSubmit={submit}>
          <input className="input" type="password" placeholder="Пароль"
                 value={pass} onChange={e => setPass(e.target.value)}
                 style={{ marginBottom: 12 }} autoFocus />
          {err && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 10 }}>{err}</p>}
          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} disabled={loading}>
            {loading ? 'Вход...' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  )
}
