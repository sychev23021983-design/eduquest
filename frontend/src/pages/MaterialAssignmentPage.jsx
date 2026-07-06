import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import { Block, groupSlides } from '../articleBlocks.jsx'
import '../game-theme.css'

export default function MaterialAssignmentPage() {
  const { id } = useParams()
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [assignment, setAssignment] = useState(null)
  const [err, setErr] = useState('')
  const [articleIdx, setArticleIdx] = useState(0)
  const [slide, setSlide] = useState(0)
  const [phase, setPhase] = useState('reading') // reading | done
  const [completing, setCompleting] = useState(false)
  const [coinsEarned, setCoinsEarned] = useState(0)
  const [alreadyDone, setAlreadyDone] = useState(false)

  useEffect(() => { load() }, [id])

  async function load() {
    setErr('')
    try {
      const a = await api.materialAssignment(token, id)
      setAssignment(a)
      setArticleIdx(0); setSlide(0)
      setPhase(a.completed_at ? 'done' : 'reading')
      setAlreadyDone(!!a.completed_at)
    } catch (e) { setErr(e.message) }
  }

  const article = assignment?.articles?.[articleIdx]
  const slides = useMemo(() => article ? groupSlides(article.blocks) : [], [article])

  useEffect(() => {
    if (article) api.markArticleRead(token, article.id).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [article?.id])

  function goNext() {
    if (slide < slides.length - 1) { setSlide(s => s + 1); return }
    if (articleIdx < (assignment.articles.length - 1)) { setArticleIdx(i => i + 1); setSlide(0); return }
    setPhase('done')
  }
  function goPrev() {
    if (slide > 0) { setSlide(s => s - 1); return }
    if (articleIdx > 0) {
      const prevArticle = assignment.articles[articleIdx - 1]
      const prevSlides = groupSlides(prevArticle.blocks)
      setArticleIdx(i => i - 1); setSlide(prevSlides.length - 1)
    }
  }

  async function complete() {
    setCompleting(true)
    try {
      const res = await api.completeMaterialAssignment(token, id)
      setCoinsEarned(res.coins_earned || 0)
      setAlreadyDone(!!res.already_completed)
    } catch (e) { setErr(e.message) }
    setCompleting(false)
  }

  if (err) return (
    <div className="game-home"><div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>😕 {err}</div></div>
  )
  if (!assignment) return (
    <div className="game-home"><div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>🔍 Открываю материалы…</div></div>
  )

  if (phase === 'done') {
    return (
      <div className="game-home">
        <div className="gh-map-topbar">
          <button className="gh-back-btn" onClick={() => nav('/')}>‹</button>
          <div className="gh-map-title"><span className="gh-map-title-text">⭐ Задание на изучение</span></div>
        </div>
        <div className="gh-wrap" style={{ paddingTop: 30, maxWidth: 640 }}>
          <div className="gh-card" style={{ textAlign: 'center', padding: '32px 20px' }}>
            <div style={{ fontSize: 48, marginBottom: 10 }}>{alreadyDone && coinsEarned === 0 ? '✅' : '🎉'}</div>
            <h2 style={{ marginBottom: 10 }}>
              {coinsEarned > 0 ? 'Награда получена!' : alreadyDone ? 'Ты уже проходил это задание' : 'Ты изучил все темы!'}
            </h2>
            <p style={{ color: 'var(--gh-muted)', marginBottom: 18 }}>
              Темы: {assignment.articles.map(a => a.title).join(', ')}
            </p>
            {coinsEarned > 0 && (
              <div className="gh-chip coin" style={{ fontSize: 16, padding: '8px 18px', marginBottom: 18, display: 'inline-block' }}>
                🪙 +{coinsEarned} монет
              </div>
            )}
            {!alreadyDone && coinsEarned === 0 && (
              <>
                <p style={{ marginBottom: 18 }}>Не забудь рассказать родителям, о чём ты узнал! Когда расскажешь — жми кнопку:</p>
                <button className="gh-btn" disabled={completing} onClick={complete}>
                  {completing ? 'Секунду…' : `Готово! Я рассказал родителям →`}
                </button>
              </>
            )}
            {(alreadyDone || coinsEarned > 0) && (
              <div>
                <button className="gh-btn" onClick={() => nav('/')}>На главную →</button>
              </div>
            )}
            <div style={{ marginTop: 14 }}>
              <button className="gh-btn sm blue" onClick={() => { setPhase('reading'); setArticleIdx(0); setSlide(0) }}>
                ← Перечитать материалы
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const cover = article.cover_image
  const isLast = slide === slides.length - 1 && articleIdx === assignment.articles.length - 1
  const curBlocks = slides[slide]?.blocks || []
  const isImageOnlySlide = curBlocks.length > 0 && curBlocks.every(b => b.type === 'image')
  const canGoPrev = slide > 0 || articleIdx > 0

  const navButtons = (
    <>
      {canGoPrev && <button className="gh-btn sm blue" style={{ flex: 1 }} onClick={goPrev}>← Назад</button>}
      <button className="gh-btn" style={{ flex: 2 }} onClick={goNext}>
        {isLast ? 'Готово →' : 'Дальше →'}
      </button>
    </>
  )

  return (
    <div className="game-home">
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">
            {MATERIAL_SUBJ_ICON[article.subject]} Материал {articleIdx + 1} из {assignment.articles.length}: {article.title}
          </span>
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
