import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ, MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import '../game-theme.css'

export default function MaterialsPage() {
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [subjects, setSubjects] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    const data = await api.materialSubjects(token)
    setSubjects(data)
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
          <span className="gh-map-title-text">📚 ПОЗНАВАТЕЛЬНЫЕ МАТЕРИАЛЫ</span>
        </div>
      </div>

      <div className="gh-wrap">
        <p style={{ color: 'var(--gh-muted)', margin: '18px 0 22px', maxWidth: 560 }}>
          Интересные факты и объяснения на разные темы — без тестов и оценок. Просто читай и узнавай новое!
        </p>

        {loading && <div className="gh-empty">🔍 Загружаю темы…</div>}

        {!loading && (
          <div className="gh-subjects-grid">
            {subjects.map(s => (
              <div key={s.key} className={`gh-subject-card ${s.key}`} onClick={() => nav(`/materials/${s.key}`)}>
                <div className="icon"><span style={{ fontSize: 56 }}>{MATERIAL_SUBJ_ICON[s.key]}</span></div>
                <div className="name">{MATERIAL_SUBJ[s.key] || s.label}</div>
                <div className="count">{s.count} {s.count === 1 ? 'материал' : 'материалов'}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
