import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'
import { SkillTaskView } from './SkillTaskView.jsx'
import '../game-theme.css'

const STORAGE_KEY = 'eduquest.skills-slideshow.v1'

function shuffle(arr) {
  const a = arr.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

// Та же логика, что и в MaterialsSlideshowPage: перемешиваем задания внутри каждой
// категории и чередуем категории так, чтобы по возможности не показывать два
// задания одной категории подряд.
function buildRandomOrder(items) {
  const groups = {}
  for (const it of items) {
    const key = it.category_id ?? '_'
    if (!groups[key]) groups[key] = []
    groups[key].push(it)
  }
  for (const key in groups) groups[key] = shuffle(groups[key])

  const order = []
  let lastKey = null
  while (order.length < items.length) {
    let keys = Object.keys(groups).filter(k => groups[k].length > 0)
    if (keys.length === 0) break
    const preferred = keys.filter(k => k !== lastKey)
    const pool = preferred.length > 0 ? preferred : keys
    const key = pool[Math.floor(Math.random() * pool.length)]
    order.push(groups[key].shift())
    lastKey = key
  }
  return order
}

function loadSavedState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function saveState(order, index) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ids: order.map(i => i.id), index }))
  } catch { /* ignore */ }
}

export default function SkillsSlideshowPage() {
  const { token } = useAuth()
  const nav = useNavigate()
  const [items, setItems] = useState(null) // null = ещё грузим
  const [index, setIndex] = useState(0)
  const [jumpValue, setJumpValue] = useState('')

  useEffect(() => { load() }, [])

  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === 'visible') load()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, index])

  async function load() {
    const found = await api.allActiveSkills(token)

    const saved = loadSavedState()
    const byId = new Map(found.map(it => [it.id, it]))
    let order
    if (saved && Array.isArray(saved.ids) && saved.ids.length === found.length &&
        saved.ids.every(u => byId.has(u))) {
      order = saved.ids.map(u => byId.get(u))
    } else {
      order = buildRandomOrder(found)
      saveState(order, 0)
    }

    const startIndex = saved && order.length > 0 ? Math.min(Math.max(saved.index || 0, 0), order.length - 1) : 0
    setItems(order)
    setIndex(startIndex)
  }

  const current = useMemo(() => (items && items.length > 0 ? items[index] : null), [items, index])

  function goTo(i) {
    if (!items || items.length === 0) return
    const clamped = Math.min(Math.max(i, 0), items.length - 1)
    setIndex(clamped)
    saveState(items, clamped)
  }
  function prev() { if (items && index > 0) goTo(index - 1) }
  function next() { if (items && index < items.length - 1) goTo(index + 1) }

  function submitJump(e) {
    e.preventDefault()
    const n = parseInt(jumpValue, 10)
    if (!Number.isNaN(n)) goTo(n - 1)
    setJumpValue('')
  }

  return (
    <div className="game-home">
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/skills')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">🎲 Слайд-шоу заданий</span>
        </div>
      </div>

      {items === null && <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>🔍 Собираю задания…</div>}

      {items !== null && items.length === 0 && (
        <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>Пока нет ни одного задания в разделе «Навыки» 🧩</div>
      )}

      {current && (
        <div className="gh-wrap" style={{ maxWidth: 900 }}>
          <div className="gh-skill-slideshow-row">
            <button className="gh-slideshow-arrow static" onClick={prev} disabled={index === 0} aria-label="Предыдущее">‹</button>
            <div style={{ flex: 1 }}>
              <div className="gh-skill-slideshow-category">{current.category_title}</div>
              <SkillTaskView key={current.id} skill={current} />
            </div>
            <button className="gh-slideshow-arrow static" onClick={next} disabled={index === items.length - 1} aria-label="Следующее">›</button>
          </div>
          <form className="gh-slideshow-counter static" onSubmit={submitJump}>
            <input
              className="gh-slideshow-jump-input"
              type="number"
              min={1}
              max={items.length}
              placeholder={String(index + 1)}
              value={jumpValue}
              onChange={e => setJumpValue(e.target.value)}
            />
            <span> / {items.length}</span>
          </form>
        </div>
      )}
    </div>
  )
}
