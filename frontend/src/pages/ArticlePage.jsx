import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import { Block, groupSlides } from '../articleBlocks.jsx'
import '../game-theme.css'


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
  const curBlocks = slides[slide].blocks
  const isImageOnlySlide = curBlocks.length > 0 && curBlocks.every(b => b.type === 'image')

  const navButtons = (
    <>
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
    </>
  )

  return (
    <div className="game-home">
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav(`/materials/${article.subject}`)}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">{MATERIAL_SUBJ_ICON[article.subject]} {article.title}</span>
        </div>
      </div>

      <div className="gh-wrap" style={{ maxWidth: 1800 }}>
        {isImageOnlySlide ? (
          <div className="art-image-only">
            <div className="gh-slide-dots">
              {slides.map((_, i) => (
                <div key={i} className={`gh-slide-dot ${i === slide ? 'active' : ''}`} onClick={() => setSlide(i)} style={{ cursor: 'pointer' }} />
              ))}
            </div>
            {curBlocks.map((b, i) => <Block key={i} b={b} settings={settings} />)}
            <div className="art-image-only-nav">{navButtons}</div>
          </div>
        ) : (
          <div className={cover ? 'art-layout with-cover' : 'art-layout'}>
            <div className="art-text-col">
              <div className="gh-slide-dots">
                {slides.map((_, i) => (
                  <div key={i} className={`gh-slide-dot ${i === slide ? 'active' : ''}`} onClick={() => setSlide(i)} style={{ cursor: 'pointer' }} />
                ))}
              </div>

              <div className="art-slide">
                {curBlocks.map((b, i) => <Block key={i} b={b} settings={settings} />)}
              </div>

              <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>{navButtons}</div>
            </div>
            {cover && (
              <div className="art-cover-col">
                <img className="art-cover-img" src={cover} alt={article.title} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
