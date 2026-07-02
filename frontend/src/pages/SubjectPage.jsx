import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

const SUBJ = { math: 'Математика', russian: 'Русский язык', science: 'Окружающий мир', history: 'История' }
const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }

// Геометрия змейки: расстояние между узлами по горизонтали и позиции по вертикали (в px)
const COL_W    = 118   // px между центрами соседних узлов по горизонтали
const NODE_D   = 58    // px диаметр кружка
const LEFT_PAD = 56     // px отступ до центра первого узла
const RIGHT_PAD = 56    // px отступ после последнего узла
const Y_CENTER = 100
const Y_TOP    = 54
const Y_BOTTOM = 148
const WRAP_H   = 202    // px общая высота дорожки (под подписи сверху/снизу)

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

export default function SubjectPage() {
  const { subject } = useParams()
  const { token } = useAuth()
  const nav = useNavigate()
  const [grade, setGrade] = useState(5)
  const [tree, setTree]   = useState([])
  const [loading, setLoading] = useState(true)
  const [soonMsg, setSoonMsg] = useState(false)

  useEffect(() => { init() }, [subject])

  async function init() {
    setLoading(true)
    const cfg = await api.config()
    const g = cfg.child_grade || 5
    setGrade(g)
    const data = await api.curriculum(token, g, subject)
    setTree(data.sections)
    setLoading(false)
  }

  function nodeState(section, topic, prevDone) {
    if (topic.completed) return 'completed'
    if (!prevDone) return 'locked'
    return topic.lesson_count > 0 ? 'available' : 'soon'
  }

  function onNodeClick(state, action) {
    if (state === 'locked') return
    if (state === 'soon') { setSoonMsg(true); setTimeout(() => setSoonMsg(false), 2000); return }
    action()
  }

  return (
    <div className="game-home">
      <div className="gh-topbar">
        <button className="gh-back-btn" onClick={() => nav('/')}>‹</button>
        <span className="gh-logo">{SUBJ_ICON[subject]} {SUBJ[subject]}</span>
        <span style={{ marginLeft: 'auto', color: 'var(--gh-muted)', fontSize: '0.85rem', fontFamily: 'var(--font-num)' }}>{grade} класс</span>
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

          if (hasIntro) {
            nodes.push({ kind: 'intro', state: s.intro_done ? 'completed' : 'available', label: 'Введение' })
          }
          s.topics.forEach((t, ti) => {
            const state = nodeState(s, t, prevDone)
            nodes.push({ kind: 'topic', topic: t, index: ti, state, label: `${si + 1}.${ti + 1} ${t.title}` })
            prevDone = t.completed
          })

          return (
            <div key={s.id} className="gh-section-block">
              <div className="gh-section-head">
                <span className="gh-section-num">{si + 1}</span>
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
                        <path d={pathD} fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="2.5"
                              strokeLinecap="round" />
                      </svg>
                      {nodes.map((n, i) => {
                        const pt = points[i]
                        const clickable = n.state === 'available' || n.state === 'completed'
                        const icon = n.kind === 'intro' ? '📖'
                          : n.state === 'completed' ? '⭐'
                          : n.state === 'locked' ? '🔒'
                          : n.state === 'soon' ? '⏳'
                          : (n.kind === 'topic' ? n.index + 1 : '•')
                        const circleClass = n.kind === 'intro' && n.state !== 'completed' ? 'intro' : n.state
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
                            <div className={`gh-node-circle ${circleClass}`}>{icon}</div>
                            <div className="gh-node-label">{n.label}</div>
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
    </div>
  )
}
