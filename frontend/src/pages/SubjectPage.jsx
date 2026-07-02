import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

const SUBJ = { math: 'Математика', russian: 'Русский язык', science: 'Окружающий мир', history: 'История' }
const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }

export default function SubjectPage() {
  const { subject } = useParams()
  const { token } = useAuth()
  const nav = useNavigate()
  const [grade, setGrade] = useState(5)
  const [tree, setTree]   = useState([])
  const [lessonsByTopic, setLessonsByTopic] = useState({})
  const [openTopic, setOpenTopic] = useState(null)
  const [loading, setLoading] = useState(true)

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

  async function toggleTopic(t) {
    if (openTopic === t.id) { setOpenTopic(null); return }
    setOpenTopic(t.id)
    if (!lessonsByTopic[t.id]) {
      const ls = await api.lessons(token, subject, t.id)
      setLessonsByTopic(m => ({ ...m, [t.id]: ls }))
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav('/')} style={{ background: 'none', border: 'none', fontSize: 20, color: '#aaa' }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>{SUBJ_ICON[subject]} {SUBJ[subject]} · {grade} класс</span>
      </div>

      <div className="page">
        {loading && <p style={{ color: 'var(--muted)' }}>Загрузка…</p>}
        {!loading && tree.length === 0 && (
          <p style={{ color: 'var(--muted)', textAlign: 'center', padding: 40 }}>
            Программа по этому предмету пока не заполнена 🚧
          </p>
        )}

        {tree.map((s, si) => (
          <div key={s.id} style={{ marginBottom: 22 }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--muted)', marginBottom: 10 }}>
              {si + 1}. {s.title.toUpperCase()}
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {s.topics.map((t, ti) => (
                <div key={t.id} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                  <div onClick={() => toggleTopic(t)} style={{ padding: '14px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontWeight: 600, flex: 1 }}>{si + 1}.{ti + 1} {t.title}</span>
                    <span style={{ fontSize: 13, color: 'var(--muted)' }}>
                      {t.lesson_count > 0 ? `📚 ${t.lesson_count} урок(ов)` : 'скоро появятся'}
                    </span>
                    <span style={{ color: 'var(--blue)', transform: openTopic === t.id ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>›</span>
                  </div>
                  {openTopic === t.id && (
                    <div style={{ borderTop: '1px solid var(--border)', padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {(lessonsByTopic[t.id] || []).map(l => (
                        <div key={l.id} onClick={() => nav(`/lesson/${l.id}`)}
                             style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10, background: 'var(--bg)', borderRadius: 8, padding: '10px 12px' }}>
                          <span style={{ flex: 1 }}>{l.topic}</span>
                          <span style={{ fontSize: 12, color: 'var(--muted)' }}>🪙 {l.coins_lesson}</span>
                          <span style={{ color: 'var(--blue)' }}>›</span>
                        </div>
                      ))}
                      {(lessonsByTopic[t.id] || []).length === 0 && (
                        <p style={{ color: 'var(--muted)', fontSize: 13, padding: '6px 4px' }}>Уроков пока нет — скоро появятся 🚀</p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
