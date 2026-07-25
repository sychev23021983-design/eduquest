import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

const CARD_COLORS = 8

export default function SkillsPage() {
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    const data = await api.skillCategories(token)
    setCategories(data)
    setLoading(false)
  }

  const pageStyle = settings?.bg_main ? {
    backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}

  return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">🧠 НАВЫКИ</span>
        </div>
      </div>

      <div className="gh-wrap">
        <p style={{ color: 'var(--gh-muted)', margin: '18px 0 22px', maxWidth: 560 }}>
          Смотри на картинку и рассуждай — если трудно, открой до трёх подсказок по очереди.
        </p>

        <button className="gh-btn" style={{ marginBottom: 22 }} onClick={() => nav('/skills/slideshow')}>
          🎲 Слайд-шоу заданий
        </button>

        {loading && <div className="gh-empty">🔍 Загружаю категории…</div>}

        {!loading && categories.length === 0 && (
          <div className="gh-card gh-empty">Пока нет ни одной категории — попроси родителя добавить 🧩</div>
        )}

        {!loading && categories.length > 0 && (
          <div className="gh-subjects-grid">
            {categories.map((c, i) => (
              <div key={c.id} className={`gh-subject-card gh-skill-card-${i % CARD_COLORS}`} onClick={() => nav(`/skills/${c.id}`)}>
                <div className="icon"><span style={{ fontSize: 56 }}>🧩</span></div>
                <div className="name">{c.title}</div>
                <div className="count">{c.count} {c.count === 1 ? 'задание' : 'заданий'}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
