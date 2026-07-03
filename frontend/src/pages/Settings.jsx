import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'

const FONT_CHOICES = ['Nunito', 'Baloo 2', 'Rubik', 'Montserrat', 'PT Sans', 'Comfortaa', 'Ubuntu']
const SUBJECTS = [
  { key: 'math', label: '🔢 Математика' },
  { key: 'russian', label: '📝 Русский язык' },
  { key: 'science', label: '🌿 Окружающий мир' },
  { key: 'history', label: '🏛️ История' },
]

function UploadRow({ label, hint, currentUrl, onUpload, uploading, previewSize = 60 }) {
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

export default function Settings() {
  const { token } = useAuth()
  const { settings, refresh } = useSettings()
  const nav = useNavigate()
  const [form, setForm] = useState(null)
  const [uploadingSlot, setUploadingSlot] = useState(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { if (settings) setForm(settings) }, [settings])

  function setF(key, val) { setForm(f => ({ ...f, [key]: val })) }

  async function uploadTo(slot, file) {
    setUploadingSlot(slot)
    try {
      const fd = new FormData(); fd.append('file', file)
      await api.uploadSettingAsset(token, slot, fd)
      const fresh = await refresh()
      setForm(fresh)
      setMsg('✅ Загружено')
    } catch (e) { setMsg('❌ ' + e.message) }
    setUploadingSlot(null)
    setTimeout(() => setMsg(''), 2500)
  }

  async function save() {
    setSaving(true)
    try {
      await api.updateSettings(token, {
        site_name: form.site_name,
        logo_size: form.logo_size,
        font_heading: form.font_heading,
        font_body: form.font_body,
        color_accent: form.color_accent,
        color_accent2: form.color_accent2,
      })
      await refresh()
      setMsg('✅ Настройки сохранены')
    } catch (e) { setMsg('❌ ' + e.message) }
    setSaving(false)
    setTimeout(() => setMsg(''), 2500)
  }

  async function resetAll() {
    if (!confirm('Сбросить все настройки оформления к значениям по умолчанию?')) return
    await api.resetSettings(token)
    const fresh = await refresh()
    setForm(fresh)
  }

  if (!form) return <div className="page" style={{ color: 'var(--muted)' }}>Загрузка…</div>

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav('/parent')} style={{ background: 'none', border: 'none', fontSize: 20, color: '#aaa' }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>⚙️ Настройки интерфейса</span>
        {msg && <span style={{ marginLeft: 'auto', color: msg.startsWith('✅') ? '#4ade80' : '#f87171', fontSize: 13 }}>{msg}</span>}
      </div>

      <div className="page-wide">
        <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 20 }}>
          Здесь можно поменять логотип, фавикон, фоновые картинки, иконки предметов, шрифты, цвета и
          изображения боковых панелей главного экрана. Изменения картинок применяются сразу, текст/цвета/шрифты — по кнопке «Сохранить».
        </p>

        {/* Общее */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 14 }}>Общее</h3>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Название сайта (в топбаре, если нет логотипа)</label>
          <input className="input" value={form.site_name || ''} onChange={e => setF('site_name', e.target.value)} style={{ marginBottom: 4 }} />
        </div>

        {/* Логотип и фавикон */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Топбар</h3>
          <UploadRow label="Логотип" hint="Показывается в шапке вместо названия. PNG/SVG с прозрачным фоном лучше всего."
                     currentUrl={form.logo_url} uploading={uploadingSlot === 'logo_url'} onUpload={f => uploadTo('logo_url', f)} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 0' }}>
            <label style={{ fontWeight: 600, fontSize: 14, minWidth: 160 }}>Высота логотипа</label>
            <input type="range" min="16" max="80" value={form.logo_size || 28}
                   onChange={e => setF('logo_size', Number(e.target.value))} style={{ flex: 1 }} />
            <span style={{ fontFamily: 'monospace', fontSize: 13, color: 'var(--muted)', width: 44 }}>{form.logo_size || 28}px</span>
          </div>
          <UploadRow label="Favicon (иконка вкладки)" hint="Квадратная картинка, отобразится в заголовке вкладки браузера."
                     currentUrl={form.favicon_url} uploading={uploadingSlot === 'favicon_url'} onUpload={f => uploadTo('favicon_url', f)} previewSize={40} />
        </div>

        {/* Фоны */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Фоны</h3>
          <UploadRow label="Общий фон страницы" hint="Растягивается на весь экран за карточками."
                     currentUrl={form.bg_main} uploading={uploadingSlot === 'bg_main'} onUpload={f => uploadTo('bg_main', f)} />
          <UploadRow label="Фон блока приветствия" hint="Баннер «Привет, ...!» на главном экране."
                     currentUrl={form.bg_hero} uploading={uploadingSlot === 'bg_hero'} onUpload={f => uploadTo('bg_hero', f)} />
          <UploadRow label="Фон блока «Урок дня»" hint="Крупная карточка с текущим уроком."
                     currentUrl={form.bg_lesson_of_day} uploading={uploadingSlot === 'bg_lesson_of_day'} onUpload={f => uploadTo('bg_lesson_of_day', f)} />
          <UploadRow label="Фон карты уроков" hint="Фон страницы со списком уроков предмета (карта-путь по темам)."
                     currentUrl={form.bg_subject_page} uploading={uploadingSlot === 'bg_subject_page'} onUpload={f => uploadTo('bg_subject_page', f)} />
        </div>

        {/* Познавательные материалы */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Познавательные материалы</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)' }}>
            Картинка для материала «Почему идёт дождь?» уже встроена в проект и ничего загружать не нужно.
            Для новых материалов обложку и картинки внутри текста можно загрузить прямо в редакторе
            материала (Кабинет родителя → 📚 Материалы → редактирование статьи).
          </p>
        </div>

        {/* Боковые панели */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Боковые панели</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
            Декоративные изображения по бокам главного экрана (как персонажи на референсе). На узких экранах скрываются автоматически.
          </p>
          <UploadRow label="Левая панель" currentUrl={form.sidebar_left_url}
                     uploading={uploadingSlot === 'sidebar_left_url'} onUpload={f => uploadTo('sidebar_left_url', f)} />
          <UploadRow label="Правая панель" currentUrl={form.sidebar_right_url}
                     uploading={uploadingSlot === 'sidebar_right_url'} onUpload={f => uploadTo('sidebar_right_url', f)} />
        </div>

        {/* Иконки предметов */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Иконки предметов</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>Заменяют emoji-иконки на карточках предметов. Без загрузки используется стандартный emoji.</p>
          {SUBJECTS.map(s => (
            <UploadRow key={s.key} label={s.label} currentUrl={form.subject_icons?.[s.key]}
                       uploading={uploadingSlot === `subject_${s.key}`} onUpload={f => uploadTo(`subject_${s.key}`, f)} previewSize={48} />
          ))}
        </div>

        {/* Шрифты и цвета */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 14 }}>Шрифты и цвета</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Шрифт заголовков / чисел</label>
              <select className="input" value={form.font_heading} onChange={e => setF('font_heading', e.target.value)}>
                {FONT_CHOICES.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Шрифт текста</label>
              <select className="input" value={form.font_body} onChange={e => setF('font_body', e.target.value)}>
                {FONT_CHOICES.filter(f => f !== 'Baloo 2').map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Основной акцентный цвет</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" value={form.color_accent} onChange={e => setF('color_accent', e.target.value)} style={{ width: 44, height: 36, border: 'none', borderRadius: 8, cursor: 'pointer' }} />
                <input className="input" value={form.color_accent} onChange={e => setF('color_accent', e.target.value)} />
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Второй акцентный цвет</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" value={form.color_accent2} onChange={e => setF('color_accent2', e.target.value)} style={{ width: 44, height: 36, border: 'none', borderRadius: 8, cursor: 'pointer' }} />
                <input className="input" value={form.color_accent2} onChange={e => setF('color_accent2', e.target.value)} />
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', paddingBottom: 40 }}>
          <button className="btn" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={resetAll}>Сбросить всё</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Сохраняю…' : '💾 Сохранить'}</button>
        </div>
      </div>
    </div>
  )
}
