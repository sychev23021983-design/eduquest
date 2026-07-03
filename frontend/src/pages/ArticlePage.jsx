import { useEffect, useMemo, useState } from 'react'
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

// Группирует блоки в слайды: каждый heading начинает новый слайд,
// всё до следующего heading относится к текущему слайду.
function groupSlides(blocks) {
  const slides = []
  let cur = null
  for (const b of blocks) {
    if (b.type === 'heading') {
      cur = { blocks: [b] }
      slides.push(cur)
    } else {
      if (!cur) { cur = { blocks: [] }; slides.push(cur) }
      cur.blocks.push(b)
    }
  }
  return slides.length > 0 ? slides : [{ blocks: [] }]
}

export default function ArticlePage() {
  const { id } = useParams()
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [article, setArticle] = useState(null)
  const [slide, setSlide] = useState(0)

  useEffect(() => { load() }, [id])

  async function load() {
    const a = await api.article(token, id)
    setArticle(a)
    setSlide(0)
    api.markArticleRead(token, id).catch(() => {})
  }

  const slides = useMemo(() => article ? groupSlides(article.blocks) : [], [article])

  if (!article) return (
    <div className="game-home">
      <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>🔍 Открываю материал…</div>
    </div>
  )

  const cover = article.cover_image
  const isLast = slide === slides.length - 1

  return (
    <div className="game-home">
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav(`/materials/${article.subject}`)}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">{MATERIAL_SUBJ_ICON[article.subject]} {article.title}</span>
        </div>
      </div>

      <div className="gh-wrap" style={{ maxWidth: 1800 }}>
        <div className={cover ? 'art-layout with-cover' : 'art-layout'}>
          <div className="art-text-col">
            <div className="gh-slide-dots">
              {slides.map((_, i) => (
                <div key={i} className={`gh-slide-dot ${i === slide ? 'active' : ''}`} onClick={() => setSlide(i)} style={{ cursor: 'pointer' }} />
              ))}
            </div>

            <div className="art-slide">
              {slides[slide].blocks.map((b, i) => <Block key={i} b={b} settings={settings} />)}
            </div>

            <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
              {slide > 0 && (
                <button className="gh-btn sm blue" style={{ flex: 1 }} onClick={() => setSlide(s => s - 1)}>← Назад</button>
              )}
              {!isLast ? (
                <button className="gh-btn" style={{ flex: 2 }} onClick={() => setSlide(s => s + 1)}>Дальше →</button>
              ) : (
                <button className="gh-btn" style={{ flex: 2 }} onClick={() => nav(`/materials/${article.subject}`)}>
                  Готово! К другим материалам →
                </button>
              )}
            </div>
          </div>
          {cover && (
            <div className="art-cover-col">
              <img className="art-cover-img" src={cover} alt={article.title} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
