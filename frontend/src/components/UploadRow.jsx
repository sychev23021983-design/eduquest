import { useRef } from 'react'

// Универсальная строка «превью + кнопка загрузки» для картинок, привязанных к именованному
// слоту в site_settings (см. POST /api/settings/upload?slot=...). Используется и в общих
// настройках оформления (Settings.jsx), и в редакторе программы для уроков-слайдшоу
// (Curriculum.jsx, раздел «Архитектура математики»).
export default function UploadRow({ label, hint, currentUrl, onUpload, uploading, previewSize = 60 }) {
  const inputRef = useRef(null)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{
        width: previewSize, height: previewSize, borderRadius: 10, background: '#f1f3f7',
        display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
        border: '1px solid var(--border)',
      }}>
        {currentUrl ? <img src={currentUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <span style={{ color: 'var(--muted)', fontSize: 11 }}>нет</span>}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{label}</div>
        {hint && <div style={{ fontSize: 12, color: 'var(--muted)' }}>{hint}</div>}
      </div>
      <input ref={inputRef} type="file" accept="image/*" style={{ display: 'none' }}
             onChange={e => { if (e.target.files[0]) onUpload(e.target.files[0]); e.target.value = '' }} />
      <button className="btn btn-sm" disabled={uploading} onClick={() => inputRef.current.click()}>
        {uploading ? 'Загрузка…' : (currentUrl ? 'Заменить' : 'Загрузить')}
      </button>
    </div>
  )
}
