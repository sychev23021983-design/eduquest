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
      const res = await api.login({ password: pass.trim(), role })
      login(res.token, res.role)
      nav(res.role === 'parent' ? '/parent' : '/')
    } catch (e) {
      setErr('Неверный пароль')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div className="card" style={{ width: 360, padding: 32 }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ fontSize: 48, marginBottom: 8 }}>🎓</div>
          <h1 style={{ fontSize: 24, fontWeight: 700 }}>EduQuest</h1>
          <p style={{ color: 'var(--muted)', fontSize: 14, marginTop: 4 }}>Образование через игру</p>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {[
            { key: 'child',  label: '🎮 Я — Тимофей' },
            { key: 'parent', label: '👨‍💼 Родитель' },
          ].map(({ key, label }) => (
            <button key={key} onClick={() => { setRole(key); setErr('') }}
              style={{
                flex: 1, padding: '10px 0', borderRadius: 8, border: '1.5px solid',
                borderColor: role === key ? 'var(--blue)' : 'var(--border)',
                background:  role === key ? 'var(--blue-light)' : '#fff',
                color:       role === key ? 'var(--blue)' : 'var(--muted)',
                fontWeight: 500, fontSize: 14, cursor: 'pointer',
              }}>
              {label}
            </button>
          ))}
        </div>

        <form onSubmit={submit}>
          <input
            className="input"
            type="password"
            placeholder={role === 'parent' ? 'Пароль родителя' : 'Пароль Тимофея'}
            value={pass}
            onChange={e => setPass(e.target.value)}
            style={{ marginBottom: 12 }}
            autoFocus
          />
          {err && (
            <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 10 }}>
              ❌ {err}
            </p>
          )}
          <button
            className="btn btn-primary"
            style={{ width: '100%', justifyContent: 'center', padding: '10px 0' }}
            disabled={loading || !pass.trim()}
          >
            {loading ? 'Вход...' : 'Войти →'}
          </button>
        </form>

        <div style={{ marginTop: 20, padding: '10px 14px', background: 'var(--bg)', borderRadius: 8, fontSize: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
          По умолчанию:<br />
          Тимофей: <code>child123</code><br />
          Родитель: <code>parent123</code>
        </div>
      </div>
    </div>
  )
}
