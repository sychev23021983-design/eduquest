import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'
import { SkillTaskView } from './SkillTaskView.jsx'
import '../game-theme.css'

export default function SkillTaskPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const categoryId = searchParams.get('category_id')
  const { token } = useAuth()
  const nav = useNavigate()
  const [skill, setSkill] = useState(null)
  const [siblings, setSiblings] = useState(null) // список заданий той же категории, для «Дальше»

  useEffect(() => { load() }, [id])

  async function load() {
    setSkill(null)
    const s = await api.skill(token, id)
    setSkill(s)
    if (categoryId) {
      api.skills(token, categoryId).then(setSiblings).catch(() => setSiblings(null))
    } else {
      setSiblings(null)
    }
  }

  const backTo = categoryId ? `/skills/${categoryId}` : '/skills'
  const idx = siblings ? siblings.findIndex(s => s.id === skill?.id) : -1
  const nextId = siblings && idx >= 0 && idx < siblings.length - 1 ? siblings[idx + 1].id : null

  if (!skill) return (
    <div className="game-home">
      <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>🔍 Открываю задание…</div>
    </div>
  )

  return (
    <div className="game-home">
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav(backTo)}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">🧩 Задание{idx >= 0 ? ` ${idx + 1} / ${siblings.length}` : ''}</span>
        </div>
      </div>

      <div className="gh-wrap" style={{ maxWidth: 1400 }}>
        <SkillTaskView key={skill.id} skill={skill} />

        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          {nextId ? (
            <button className="gh-btn" style={{ flex: 1 }} onClick={() => nav(`/skills/task/${nextId}?category_id=${categoryId}`)}>
              Дальше →
            </button>
          ) : (
            <button className="gh-btn" style={{ flex: 1 }} onClick={() => nav(backTo)}>
              Готово! Назад к категории →
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
