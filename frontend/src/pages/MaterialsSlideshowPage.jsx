import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

function shuffle(arr) {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

export default function MaterialsSlideshowPage() {
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [images, setImages] = useState(null) // null = ещё грузим
  const [index, setIndex] = useState(0)
  const [isLong, setIsLong] = useState(false)

  useEffect(() => { load() }, [])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [images])

  async function load() {
    const list = await api.articles(token)
    const found = []
    const seen = new Set()

    function add(url, caption) {
      if (!url || seen.has(url)) return
      seen.add(url)
      found.push({ url, caption })
    }

    for (const a of list) {
      add(a.cover_image, a.title)
    }

    // Заглядываем в каждую статью, чтобы найти картинки, вставленные прямо в текст (тип "image")
    const details = await Promise.all(list.map(a => api.article(token, a.id).catch(() => null)))
    for (const a of details) {
      if (!a?.blocks) continue
      for (const b of a.blocks) {
        if (b.type === 'image') {
          const src = b.url || settings?.[b.slot]
          add(src, b.caption || a.title)
        }
      }
    }

    setImages(shuffle(found))
    setIndex(0)
  }

  const current = useMemo(() => (images && images.length > 0 ? images[index] : null), [images, index])

  function prev() {
    if (!images || images.length === 0) return
    setIsLong(false)
    setIndex(i => (i - 1 + images.length) % images.length)
  }
  function next() {
    if (!images || images.length === 0) return
    setIsLong(false)
    setIndex(i => (i + 1) % images.length)
  }

  function onImgLoad(e) {
    const { naturalWidth, naturalHeight } = e.target
    setIsLong(naturalHeight > naturalWidth)
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
          <button className="gh-slideshow-arrow prev" onClick={prev} aria-label="Предыдущая">‹</button>
          <div className={`gh-slideshow-img-box ${isLong ? 'long' : ''}`}>
            <img src={current.url} alt={current.caption || ''} onLoad={onImgLoad} />
          </div>
          <button className="gh-slideshow-arrow next" onClick={next} aria-label="Следующая">›</button>
        </div>
      )}
    </div>
  )
}
