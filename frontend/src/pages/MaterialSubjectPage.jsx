import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ, MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import '../game-theme.css'

export default function MaterialSubjectPage() {
  const { subject } = useParams()
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [subject])

  async function load() {
    setLoading(true)
    const data = await api.articles(token, subject)
    setArticles(data)
    setLoading(false)
  }

  const pageStyle = settings?.bg_main ? {
    backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}

  return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/materials')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">{MATERIAL_SUBJ_ICON[subject]} {(MATERIAL_SUBJ[subject] || '').toUpperCase()}</span>
        </div>
      </div>

      <div className="gh-wrap">
        {loading && <div className="gh-empty">🔍 Загружаю материалы…</div>}

        {!loading && articles.length === 0 && (
          <div className="gh-card gh-empty" style={{ marginTop: 20 }}>Материалов по этой теме пока нет 🚧</div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 18 }}>
          {articles.map(a => (
            <div key={a.id} className="gh-card" style={{ display: 'flex', alignItems: 'center', gap: 14, cursor: 'pointer' }}
                 onClick={() => nav(`/materials/article/${a.id}`)}>
              <span style={{ fontSize: 28, flexShrink: 0 }}>{MATERIAL_SUBJ_ICON[subject]}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>{a.title}</div>
                {a.summary && <div style={{ fontSize: '0.82rem', color: 'var(--gh-muted)' }}>{a.summary}</div>}
              </div>
              {a.read && <span style={{ fontSize: '0.72rem', color: 'var(--gh-green)', fontWeight: 700, whiteSpace: 'nowrap' }}>✓ прочитано</span>}
              <span style={{ color: 'var(--gh-blue)', fontSize: 20 }}>›</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
