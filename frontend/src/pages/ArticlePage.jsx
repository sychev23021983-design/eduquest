import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import '../game-theme.css'

function Block({ b, settings }) {
  switch (b.type) {
    case 'heading':
      return <h2 className="art-h">{b.text}</h2>
    case 'subheading':
      return <h3 className="art-h3">{b.text}</h3>
    case 'paragraph':
      return <p className="art-p">{b.text}</p>
    case 'callout':
      return <div className="art-callout">{b.text}</div>
    case 'flow':
      return <div className="art-flow">{b.text}</div>
    case 'list':
      return <ul className="art-list">{b.items.map((it, i) => <li key={i}>{it}</li>)}</ul>
    case 'checklist':
      return (
        <ul className="art-checklist">
          {b.items.map((it, i) => <li key={i}><span className="ck">✅</span>{it}</li>)}
        </ul>
      )
    case 'experiment':
      return (
        <div className="art-experiment">
          <div className="art-experiment-title">🧪 {b.title}</div>
          {b.materials?.length > 0 && (
            <>
              <div className="art-experiment-label">Тебе понадобится:</div>
              <ul className="art-list">{b.materials.map((m, i) => <li key={i}>{m}</li>)}</ul>
            </>
          )}
          {b.steps?.length > 0 && (
            <>
              <div className="art-experiment-label">Что делать:</div>
              <ol className="art-steps">{b.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            </>
          )}
          {b.result && (
            <div className="art-experiment-result"><b>Что произойдёт?</b> {b.result}</div>
          )}
        </div>
      )
    case 'question':
      return <div className="art-question">💭 <b>Подумай:</b> {b.text}</div>
    case 'image': {
      const src = b.url || settings?.[b.slot]
      if (!src) return (
        <div className="art-image-placeholder">🖼️ Картинка «{b.caption || b.slot}» скоро появится</div>
      )
      return (
        <figure className="art-figure">
          <img src={src} alt={b.caption || ''} />
          {b.caption && <figcaption>{b.caption}</figcaption>}
        </figure>
      )
    }
    default:
      return null
  }
}

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

  const cover = article.cover_image

  return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav(`/materials/${article.subject}`)}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">{MATERIAL_SUBJ_ICON[article.subject]} {article.title}</span>
        </div>
      </div>

      <div className="gh-wrap" style={{ maxWidth: 1100 }}>
        <div className={cover ? 'art-layout with-cover' : 'art-layout'}>
          <div className="art-text-col">
            {article.blocks.map((b, i) => <Block key={i} b={b} settings={settings} />)}
          </div>
          {cover && (
            <div className="art-cover-col">
              <img className="art-cover-img" src={cover} alt={article.title} />
            </div>
          )}
        </div>

        <button className="gh-btn" style={{ margin: '18px 0 30px' }} onClick={() => nav(`/materials/${article.subject}`)}>
          ← К другим материалам
        </button>
      </div>
    </div>
  )
}
