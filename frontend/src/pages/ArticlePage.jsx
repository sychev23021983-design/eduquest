import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import '../game-theme.css'

export default function ArticlePage() {
  const { id } = useParams()
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [article, setArticle] = useState(null)

  useEffect(() => { load() }, [id])

  async function load() {
    const a = await api.article(token, id)
    setArticle(a)
    api.markArticleRead(token, id).catch(() => {})
  }

  const pageStyle = settings?.bg_main ? {
    backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}

  if (!article) return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>🔍 Открываю материал…</div>
    </div>
  )

  return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav(`/materials/${article.subject}`)}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">{MATERIAL_SUBJ_ICON[article.subject]} {article.title}</span>
        </div>
      </div>

      <div className="gh-wrap" style={{ maxWidth: 760 }}>
        <div className="gh-card" style={{ marginTop: 20, padding: '28px 26px' }}>
          {article.blocks.map((b, i) => {
            if (b.type === 'heading') {
              return <h2 key={i} style={{ fontFamily: 'var(--font-fun)', fontSize: '1.3rem', margin: i === 0 ? '0 0 14px' : '26px 0 12px' }}>{b.text}</h2>
            }
            if (b.type === 'paragraph') {
              return <p key={i} style={{ lineHeight: 1.7, color: 'var(--gh-text)', marginBottom: 14, fontSize: '0.98rem' }}>{b.text}</p>
            }
            if (b.type === 'callout') {
              return (
                <div key={i} style={{
                  background: 'rgba(255,201,77,0.12)', border: '1px solid rgba(255,201,77,0.35)',
                  borderRadius: 12, padding: '14px 16px', margin: '4px 0 18px', fontSize: '0.92rem', lineHeight: 1.6,
                }}>{b.text}</div>
              )
            }
            if (b.type === 'image') {
              const src = settings?.[b.slot]
              if (!src) return (
                <div key={i} style={{
                  border: '1px dashed var(--gh-border)', borderRadius: 12, padding: '30px 16px',
                  textAlign: 'center', color: 'var(--gh-muted)', fontSize: '0.82rem', margin: '4px 0 18px',
                }}>
                  🖼️ Картинка «{b.caption || b.slot}» скоро появится
                </div>
              )
              return (
                <figure key={i} style={{ margin: '4px 0 18px' }}>
                  <img src={src} alt={b.caption || ''} style={{ width: '100%', borderRadius: 12, display: 'block' }} />
                  {b.caption && <figcaption style={{ fontSize: '0.78rem', color: 'var(--gh-muted)', textAlign: 'center', marginTop: 6 }}>{b.caption}</figcaption>}
                </figure>
              )
            }
            return null
          })}
        </div>

        <button className="gh-btn" style={{ margin: '18px 0 30px' }} onClick={() => nav(`/materials/${article.subject}`)}>
          ← К другим материалам
        </button>
      </div>
    </div>
  )
}
