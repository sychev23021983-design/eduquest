import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

const SUBJ = { math: 'Математика', russian: 'Русский язык', science: 'Окружающий мир', history: 'История' }
const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }

// Геометрия змейки: расстояние между узлами по горизонтали и позиции по вертикали (в px)
const COL_W    = 150   // px между центрами соседних узлов по горизонтали
const LEFT_PAD = 66     // px отступ до центра первого узла
const RIGHT_PAD = 66    // px отступ после последнего узла
const Y_CENTER = 128
const Y_TOP    = 64
const Y_BOTTOM = 196
const WRAP_H   = 268    // px общая высота дорожки (под подписи и звёзды)

function yForIndex(i, isFirstIntro) {
  // Первый узел (Введение) — по центру, дальше — плавная волна вверх/вниз
  if (isFirstIntro && i === 0) return Y_CENTER
  const topicIdx = isFirstIntro ? i - 1 : i
  return topicIdx % 2 === 0 ? Y_TOP : Y_BOTTOM
}

function buildSnakePath(points) {
  if (points.length < 2) return ''
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length; i++) {
    const p0 = points[i - 1], p1 = points[i]
    const dx = (p1.x - p0.x) / 2
    d += ` C ${p0.x + dx} ${p0.y}, ${p1.x - dx} ${p1.y}, ${p1.x} ${p1.y}`
  }
  return d
}

function Stars({ n }) {
  return (
    <div className="gh-node-stars">
      {[1, 2, 3].map(i => <span key={i} className={i <= n ? 'on' : 'off'}>★</span>)}
    </div>
  )
}

export default function SubjectPage() {
  const { subject } = useParams()
  const { token, logout } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [grade, setGrade] = useState(5)
  const [tree, setTree]   = useState([])
  const [config, setConfig] = useState({ child_name: '' })
  const [balance, setBalance] = useState({ balance: 0 })
  const [loading, setLoading] = useState(true)
  const [soonMsg, setSoonMsg] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => { init() }, [subject])

  async function init() {
    setLoading(true)
    const [cfg, bal] = await Promise.all([api.config(), api.balance(token)])
    const g = cfg.child_grade || 5
    setGrade(g)
    setConfig(cfg)
    setBalance(bal)
    const data = await api.curriculum(token, g, subject)
    setTree(data.sections)
    setLoading(false)
  }

  function nodeState(topic, prevDone) {
    if (topic.completed) return 'completed'
    if (!prevDone) return 'locked'
    return topic.lesson_count > 0 ? 'available' : 'soon'
  }

  function onNodeClick(state, action) {
    if (state === 'locked') return
    if (state === 'soon') { setSoonMsg(true); setTimeout(() => setSoonMsg(false), 2000); return }
    action()
  }

  const stats = useMemo(() => {
    let totalStars = 0, totalTopics = 0, completedTopics = 0, nextLessonId = null
    for (const s of tree) {
      let prevDone = s.intro ? s.intro_done : true
      for (const t of s.topics) {
        totalTopics++
        if (t.completed) completedTopics++
        totalStars += t.stars || 0
        const state = nodeState(t, prevDone)
        if (!nextLessonId && state === 'available') nextLessonId = t.lessons[0]?.id
        prevDone = t.completed
      }
    }
    return {
      totalStars, totalTopics, completedTopics, nextLessonId,
      pct: totalTopics ? Math.round((completedTopics / totalTopics) * 100) : 0,
    }
  }, [tree])

  const pageStyle = settings?.bg_subject_page ? {
    backgroundImage: `linear-gradient(180deg, rgba(9,11,26,0.4), rgba(9,11,26,0.6)), url(${settings.bg_subject_page})`,
    backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}

  return (
    <div className="game-home gh-map-page" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">{SUBJ_ICON[subject]} {(SUBJ[subject] || '').toUpperCase()}</span>
          <span className="gh-map-grade-pill">{grade} КЛАСС</span>
        </div>
        <div className="gh-map-right">
          <span className="gh-map-pill star"><span className="ic">⭐</span>{stats.totalStars}</span>
          <span className="gh-map-pill coin"><span className="ic">🪙</span>{balance.balance || 0}</span>
          <div className="gh-map-avatar">
            <div className="gh-map-avatar-circle">{(config.child_name || '?').charAt(0).toUpperCase()}</div>
            <div className="gh-map-avatar-info">
              <div className="name">{config.child_name || 'Ученик'}</div>
              <div className="role">Ученик</div>
            </div>
          </div>
          <div className="gh-map-menu-wrap">
            <button className="gh-map-menu-btn" onClick={() => setMenuOpen(o => !o)}>☰</button>
            {menuOpen && (
              <div className="gh-map-menu-dropdown">
                <button onClick={() => nav('/')}>🏠 Главная</button>
                <button onClick={logout}>🚪 Выйти</button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="gh-wrap">
        {loading && <div className="gh-empty">🔍 Загружаю карту тем…</div>}
        {!loading && tree.length === 0 && (
          <div className="gh-card gh-empty">Программа по этому предмету пока не заполнена 🚧</div>
        )}

        {soonMsg && (
          <div style={{
            position: 'fixed', top: 70, left: '50%', transform: 'translateX(-50%)', zIndex: 100,
            background: 'var(--gh-card-hi)', border: '1px solid var(--gh-border)', borderRadius: 12,
            padding: '10px 18px', fontWeight: 700, fontSize: '0.85rem', boxShadow: '0 8px 20px rgba(0,0,0,0.4)'
          }}>
            🤖 Этот урок ещё не готов — скоро появится!
          </div>
        )}

        {tree.map((s, si) => {
          const hasIntro = !!s.intro
          let prevDone = hasIntro ? s.intro_done : true
          const nodes = []
          const colorClass = `c${si % 4}`

          if (hasIntro) {
            nodes.push({ kind: 'intro', state: s.intro_done ? 'completed' : 'available', badge: '📖', title: 'Введение' })
          }
          s.topics.forEach((t, ti) => {
            const state = nodeState(t, prevDone)
            nodes.push({
              kind: 'topic', topic: t, state,
              badge: `${si + 1}.${ti + 1}`, title: t.title,
              stars: t.stars || 0,
            })
            prevDone = t.completed
          })

          return (
            <div key={s.id} className="gh-section-block">
              <div className={`gh-map-section-bar ${colorClass}`}>
                <span className={`gh-map-section-num ${colorClass}`}>{si + 1}</span>
                {s.title}
              </div>

              {(() => {
                const isFirstIntro = hasIntro
                const points = nodes.map((n, i) => ({
                  x: LEFT_PAD + i * COL_W,
                  y: yForIndex(i, isFirstIntro),
                }))
                const containerW = LEFT_PAD + (nodes.length - 1) * COL_W + RIGHT_PAD
                const pathD = buildSnakePath(points)

                return (
                  <div className="gh-path-scroll">
                    <div className="gh-path-wrap" style={{ width: containerW, height: WRAP_H }}>
                      <svg className="gh-path-svg" viewBox={`0 0 ${containerW} ${WRAP_H}`}>
                        <path d={pathD} fill="none" stroke="rgba(255,255,255,0.22)" strokeWidth="3"
                              strokeLinecap="round" />
                      </svg>
                      {nodes.map((n, i) => {
                        const pt = points[i]
                        const clickable = n.state === 'available' || n.state === 'completed'
                        const hexClass = n.kind === 'intro'
                          ? 'intro'
                          : n.state === 'completed' ? 'done'
                          : n.state === 'locked' ? 'locked'
                          : n.state === 'soon' ? 'soon'
                          : `avail ${colorClass}`
                        const content = n.kind === 'intro' ? n.badge
                          : n.state === 'locked' ? '🔒'
                          : n.state === 'soon' ? '⏳'
                          : n.badge
                        const action = n.kind === 'intro'
                          ? () => nav(`/subject/${subject}/intro/${s.id}`)
                          : () => nav(`/lesson/${n.topic.lessons[0].id}`)
                        return (
                          <div
                            key={i}
                            className={`gh-node-abs ${clickable ? 'clickable' : n.state}`}
                            style={{ left: pt.x, top: pt.y }}
                            onClick={() => onNodeClick(n.state, action)}
                          >
                            <div className={`gh-node-hex ${hexClass}`}>{content}</div>
                            <div className="gh-node-label">{n.title}</div>
                            {n.kind === 'topic' && n.state !== 'locked' && n.state !== 'soon' && <Stars n={n.stars} />}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })()}
            </div>
          )
        })}
      </div>

      {!loading && tree.length > 0 && (
        <div className="gh-map-progress-card">
          <h4>Твой прогресс</h4>
          <div className="gh-map-progress-row">
            <div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: `${stats.pct}%` }} /></div>
            <span className="pct">{stats.pct}%</span>
          </div>
          {stats.nextLessonId ? (
            <button className="gh-btn" style={{ width: '100%', justifyContent: 'center' }}
                    onClick={() => nav(`/lesson/${stats.nextLessonId}`)}>
              ⭐ Продолжить
            </button>
          ) : (
            <div style={{ fontSize: '0.78rem', color: 'var(--gh-muted)', textAlign: 'center' }}>
              {stats.pct === 100 ? '🎉 Всё пройдено!' : 'Пока нет доступных уроков'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
