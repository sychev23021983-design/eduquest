import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

export default function SkillCategoryPage() {
  const { categoryId } = useParams()
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [category, setCategory] = useState(null)
  const [skills, setSkills] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [categoryId])

  async function load() {
    setLoading(true)
    const [cats, list] = await Promise.all([
      api.skillCategories(token),
      api.skills(token, categoryId),
    ])
    setCategory(cats.find(c => String(c.id) === String(categoryId)) || null)
    setSkills(list)
    setLoading(false)
  }

  const pageStyle = settings?.bg_main ? {
    backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}

  return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/skills')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">🧩 {(category?.title || '').toUpperCase()}</span>
        </div>
      </div>

      <div className="gh-wrap">
        {loading && <div className="gh-empty">🔍 Загружаю задания…</div>}

        {!loading && skills.length === 0 && (
          <div className="gh-card gh-empty" style={{ marginTop: 20 }}>Заданий в этой категории пока нет 🚧</div>
        )}

        {!loading && skills.length > 0 && (
          <div className="gh-skill-grid">
            {skills.map((s, i) => (
              <div key={s.id} className="gh-skill-thumb" onClick={() => nav(`/skills/task/${s.id}?category_id=${categoryId}`)}>
                {s.image_url
                  ? <img src={s.image_url} alt="" />
                  : <span style={{ fontSize: 28 }}>🧩</span>}
                <span className="gh-skill-thumb-num">{i + 1}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
