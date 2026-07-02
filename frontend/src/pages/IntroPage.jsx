import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

export default function IntroPage() {
  const { subject, sectionId } = useParams()
  const { token } = useAuth()
  const nav = useNavigate()
  const [section, setSection] = useState(null)
  const [slides, setSlides]   = useState([])
  const [current, setCurrent] = useState(0)
  const [finishing, setFinishing] = useState(false)

  useEffect(() => { load() }, [sectionId])

  async function load() {
    const s = await api.section(token, sectionId)
    setSection(s)
    const parts = (s.intro || '').split(/\n\s*\n/).map(p => p.trim()).filter(Boolean)
    setSlides(parts.length > 0 ? parts : ['Введение скоро появится.'])
  }

  async function finish() {
    setFinishing(true)
    try { await api.completeIntro(token, sectionId) } catch { /* noop */ }
    nav(`/subject/${subject}`)
  }

  if (!section) return (
    <div className="game-home"><div className="gh-wrap gh-empty">📖 Открываю введение…</div></div>
  )

  const isLast = current === slides.length - 1

  return (
    <div className="game-home">
      <div className="gh-topbar">
        <button className="gh-back-btn" onClick={() => nav(`/subject/${subject}`)}>‹</button>
        <span className="gh-logo">📖 Введение</span>
      </div>

      <div className="gh-wrap" style={{ maxWidth: 620 }}>
        <div style={{ textAlign: 'center', marginBottom: 18 }}>
          <div style={{ fontSize: 40, marginBottom: 6 }}>📖</div>
          <h1 style={{ fontFamily: 'var(--font-num)', fontSize: '1.3rem', fontWeight: 800 }}>{section.title}</h1>
          <p style={{ color: 'var(--gh-muted)', fontSize: '0.9rem' }}>Что это, зачем и почему без этого не обойтись</p>
        </div>

        <div className="gh-slide-dots">
          {slides.map((_, i) => <div key={i} className={`gh-slide-dot ${i === current ? 'active' : ''}`} />)}
        </div>

        <div className="gh-slide-card">
          <div className="gh-slide-eyebrow">
            {current === 0 ? '💡 ЗАЧЕМ ЭТО ЗНАТЬ' : `ФАКТ ${current + 1} ИЗ ${slides.length}`}
          </div>
          <div className="gh-slide-text">{slides[current]}</div>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          {current > 0 && (
            <button className="gh-btn sm blue" style={{ flex: 1 }} onClick={() => setCurrent(c => c - 1)}>← Назад</button>
          )}
          {!isLast ? (
            <button className="gh-btn" style={{ flex: 2 }} onClick={() => setCurrent(c => c + 1)}>Дальше →</button>
          ) : (
            <button className="gh-btn" style={{ flex: 2 }} onClick={finish} disabled={finishing}>
              {finishing ? 'Записываю…' : 'Понятно! Начать тему →'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
