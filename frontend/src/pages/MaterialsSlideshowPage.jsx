import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

const STORAGE_KEY = 'eduquest.slideshow.v1'

function shuffle(arr) {
  const a = arr.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

// Строит случайный порядок слайдов так, чтобы внутри каждого раздела (subject)
// картинки не повторялись и шли в случайном порядке, а сами разделы вперемешку
// чередовались друг с другом (по возможности не показывая два слайда одного
// раздела подряд).
function buildRandomOrder(images) {
  const groups = {}
  for (const img of images) {
    const key = img.subject || '_'
    if (!groups[key]) groups[key] = []
    groups[key].push(img)
  }
  for (const key in groups) groups[key] = shuffle(groups[key])

  const order = []
  let lastKey = null
  while (order.length < images.length) {
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
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ urls: order.map(i => i.url), index }))
  } catch { /* ignore */ }
}

export default function MaterialsSlideshowPage() {
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [images, setImages] = useState(null) // null = ещё грузим
  const [index, setIndex] = useState(0)
  const [isLong, setIsLong] = useState(false)
  const [imgReady, setImgReady] = useState(false)
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
  }, [images, index])

  async function load() {
    const list = await api.articles(token)
    const found = []
    const seen = new Set()

    function add(url, caption, subject) {
      if (!url || seen.has(url)) return
      seen.add(url)
      found.push({ url, caption, subject })
    }

    for (const a of list) {
      add(a.cover_image, a.title, a.subject)
    }

    // Заглядываем в каждую статью, чтобы найти картинки, вставленные прямо в текст (тип "image")
    const details = await Promise.all(list.map(a => api.article(token, a.id).catch(() => null)))
    for (const a of details) {
      if (!a?.blocks) continue
      for (const b of a.blocks) {
        if (b.type === 'image') {
          const src = b.url || settings?.[b.slot]
          add(src, b.caption || a.title, a.subject)
        }
      }
    }

    // Пытаемся продолжить с того же места и в том же порядке, если набор картинок
    // не изменился с прошлого раза; иначе строим новый случайный порядок.
    const saved = loadSavedState()
    const byUrl = new Map(found.map(img => [img.url, img]))
    let order
    if (saved && Array.isArray(saved.urls) && saved.urls.length === found.length &&
        saved.urls.every(u => byUrl.has(u))) {
      order = saved.urls.map(u => byUrl.get(u))
    } else {
      order = buildRandomOrder(found)
      saveState(order, 0)
    }

    const startIndex = saved && order.length > 0 ? Math.min(Math.max(saved.index || 0, 0), order.length - 1) : 0
    setImages(order)
    setIndex(startIndex)
  }

  const current = useMemo(() => (images && images.length > 0 ? images[index] : null), [images, index])

  // Заранее (до показа) выясняем реальные размеры картинки — чтобы применить нужный класс
  // (обычная/«длинная») сразу, а не после отрисовки, иначе картинка на миг показывается
  // в неверном размере и «прыгает» при подгрузке.
  useEffect(() => {
    if (!current) return
    let cancelled = false
    setImgReady(false)
    const probe = new Image()
    probe.onload = () => {
      if (cancelled) return
      setIsLong(probe.naturalHeight > probe.naturalWidth)
      setImgReady(true)
    }
    probe.onerror = () => { if (!cancelled) setImgReady(true) }
    probe.src = current.url
    return () => { cancelled = true }
  }, [current?.url])

  function goTo(i) {
    if (!images || images.length === 0) return
    const clamped = Math.min(Math.max(i, 0), images.length - 1)
    setIndex(clamped)
    saveState(images, clamped)
  }
  function prev() { if (images && index > 0) goTo(index - 1) }
  function next() { if (images && index < images.length - 1) goTo(index + 1) }

  function submitJump(e) {
    e.preventDefault()
    const n = parseInt(jumpValue, 10)
    if (!Number.isNaN(n)) goTo(n - 1)
    setJumpValue('')
  }

  return (
    <div className="game-home">
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/materials')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">🎞️ Слайд-шоу картинок</span>
        </div>
      </div>

      {images === null && <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>🔍 Собираю картинки…</div>}

      {images !== null && images.length === 0 && (
        <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>Пока нет ни одной загруженной картинки в материалах 🖼️</div>
      )}

      {current && (
        <div className="gh-slideshow-wrap">
          <button className="gh-slideshow-arrow prev" onClick={prev} disabled={index === 0} aria-label="Предыдущая">‹</button>
          <div className={`gh-slideshow-img-box ${isLong ? 'long' : ''}`} style={{ visibility: imgReady ? 'visible' : 'hidden' }}>
            <img src={current.url} alt={current.caption || ''} />
          </div>
          <button className="gh-slideshow-arrow next" onClick={next} disabled={index === images.length - 1} aria-label="Следующая">›</button>
          <form className="gh-slideshow-counter" onSubmit={submitJump}>
            <input
              className="gh-slideshow-jump-input"
              type="number"
              min={1}
              max={images.length}
              placeholder={String(index + 1)}
              value={jumpValue}
              onChange={e => setJumpValue(e.target.value)}
            />
            <span> / {images.length}</span>
          </form>
        </div>
      )}
    </div>
  )
}

