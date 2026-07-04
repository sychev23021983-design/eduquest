import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ } from '../materialSubjects.js'

const BLOCKS_HELP = `Массив блоков, например:
[
  {"type": "heading", "text": "Заголовок"},
  {"type": "subheading", "text": "Подзаголовок поменьше"},
  {"type": "paragraph", "text": "Текст абзаца..."},
  {"type": "callout", "text": "Интересный факт..."},
  {"type": "flow", "text": "Океан → Испарение → Облако → Дождь"},
  {"type": "list", "items": ["Пункт 1", "Пункт 2"]},
  {"type": "checklist", "items": ["Что усвоили 1", "Что усвоили 2"]},
  {"type": "experiment", "title": "Название опыта", "materials": ["..."], "steps": ["..."], "result": "Что произойдёт"},
  {"type": "question", "text": "Вопрос для размышления"},
  {"type": "image", "slot": "material_moya_tema_1", "caption": "Подпись под картинкой"}
]
Типы блоков: heading, subheading, paragraph, callout, flow, list, checklist, experiment, question, image
(slot — уникальное имя слота для загрузки картинки внутри текста; для картинки-обложки сбоку статьи используй поле «Обложка» ниже).`

const emptyBlocksText = JSON.stringify([
  { type: 'heading', text: 'Заголовок' },
  { type: 'paragraph', text: 'Текст...' },
], null, 2)

export default function ArticleEditor() {
  const { id } = useParams()
  const isNew = !id
  const { token } = useAuth()
  const { settings, refresh: reloadSettings } = useSettings()
  const nav = useNavigate()
  const fileInputs = useRef({})

  const [list, setList] = useState([])
  const [form, setForm] = useState({ subject: 'biology', grade: 5, title: '', summary: '', cover_image: '' })
  const [blocksText, setBlocksText] = useState(emptyBlocksText)
  const [jsonErr, setJsonErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [uploadingSlot, setUploadingSlot] = useState(null)

  useEffect(() => { if (isNew) loadList(); else loadArticle() }, [id])

  async function loadList() {
    const all = await Promise.all(Object.keys(MATERIAL_SUBJ).map(s => api.articles(token, s)))
    setList(all.flat())
  }

  async function loadArticle() {
    const a = await api.article(token, id)
    setForm({ subject: a.subject, grade: a.grade || 5, title: a.title, summary: a.summary || '', cover_image: a.cover_image || '' })
    setBlocksText(JSON.stringify(a.blocks, null, 2))
  }

  function setF(key, val) { setForm(f => ({ ...f, [key]: val })) }

  const newSlotId = useRef(Math.random().toString(36).slice(2, 10))
  const coverSlot = id ? `article_cover_${id}` : `article_cover_new_${newSlotId.current}`

  async function uploadCover(file) {
    setUploadingSlot(coverSlot)
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await api.uploadSettingAsset(token, coverSlot, fd)
      const newCover = res[coverSlot]
      setF('cover_image', newCover)
      await reloadSettings?.()
      if (!isNew) {
        // Сразу сохраняем обложку в самой статье — иначе она хранится только в настройках-слоте
        // и «слетает» при перезагрузке страницы до нажатия кнопки «Сохранить».
        const blocks = parsedBlocks() || []
        await api.updateArticle(token, id, {
          subject: form.subject, grade: Number(form.grade) || null,
          title: form.title.trim(), summary: form.summary, cover_image: newCover, blocks,
        })
        setMsg('✅ Обложка загружена и сохранена')
      } else {
        setMsg('✅ Обложка загружена (сохранится вместе со статьёй по кнопке ниже)')
      }
    } catch (e) { setMsg('❌ ' + e.message) }
    setUploadingSlot(null)
    setTimeout(() => setMsg(''), 2500)
  }

  function parsedBlocks() {
    try { return JSON.parse(blocksText) } catch { return null }
  }

  const imageSlots = (() => {
    const blocks = parsedBlocks()
    if (!Array.isArray(blocks)) return []
    return blocks.filter(b => b.type === 'image' && b.slot).map(b => ({ slot: b.slot, caption: b.caption }))
  })()

  async function uploadSlot(slot, file) {
    setUploadingSlot(slot)
    try {
      const fd = new FormData(); fd.append('file', file)
      await api.uploadSettingAsset(token, slot, fd)
      await reloadSettings?.()
      setMsg('✅ Картинка загружена')
    } catch (e) { setMsg('❌ ' + e.message) }
    setUploadingSlot(null)
    setTimeout(() => setMsg(''), 2500)
  }

  async function save() {
    setJsonErr('')
    const blocks = parsedBlocks()
    if (!blocks) { setJsonErr('Ошибка в JSON блоков — проверь синтаксис.'); return }
    if (!form.title.trim()) { setJsonErr('Укажи заголовок материала.'); return }
    setSaving(true)
    try {
      const payload = { subject: form.subject, grade: Number(form.grade) || null, title: form.title.trim(), summary: form.summary, cover_image: form.cover_image || null, blocks }
      if (isNew) {
        const res = await api.createArticle(token, payload)
        setMsg('✅ Материал создан')
        nav(`/parent/materials/${res.id}/edit`)
      } else {
        await api.updateArticle(token, id, payload)
        setMsg('✅ Сохранено')
      }
    } catch (e) { setMsg('❌ ' + e.message) }
    setSaving(false)
    setTimeout(() => setMsg(''), 2500)
  }

  async function remove(articleId) {
    if (!confirm('Удалить материал?')) return
    await api.deleteArticle(token, articleId)
    loadList()
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav('/parent')} style={{ background: 'none', border: 'none', fontSize: 20, color: '#aaa' }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>📚 Познавательные материалы</span>
        {msg && <span style={{ marginLeft: 'auto', color: msg.startsWith('✅') ? '#4ade80' : '#f87171', fontSize: 13 }}>{msg}</span>}
      </div>

      <div className="page-wide">

        {isNew && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontWeight: 600 }}>Все материалы ({list.length})</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
              {list.map(a => (
                <div key={a.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <span className="badge">{MATERIAL_SUBJ[a.subject]}</span>
                    <div style={{ fontWeight: 500, marginTop: 2 }}>{a.title}</div>
                    {a.summary && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{a.summary}</div>}
                  </div>
                  <button className="btn btn-sm" onClick={() => window.open(`/materials/article/${a.id}`, '_blank')}>👁 Посмотреть</button>
                  <button className="btn btn-sm" onClick={() => nav(`/parent/materials/${a.id}/edit`)}>✏️ Изменить</button>
                  <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => remove(a.id)}>🗑️</button>
                </div>
              ))}
              {list.length === 0 && (
                <div className="card" style={{ textAlign: 'center', padding: 40, color: 'var(--muted)' }}>
                  Материалов пока нет — создай первый ниже 👇
                </div>
              )}
            </div>
            <h3 style={{ fontWeight: 600, marginBottom: 12 }}>➕ Новый материал</h3>
          </>
        )}

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 14 }}>Основное</h3>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Предмет</label>
          <select className="input" value={form.subject} onChange={e => setF('subject', e.target.value)} style={{ marginBottom: 12 }}>
            {Object.entries(MATERIAL_SUBJ).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Класс (необязательно)</label>
          <input className="input" type="number" value={form.grade} onChange={e => setF('grade', e.target.value)} style={{ width: 120, marginBottom: 12 }} />
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Заголовок</label>
          <input className="input" value={form.title} onChange={e => setF('title', e.target.value)} style={{ marginBottom: 12 }} />
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Краткое описание (показывается в списке)</label>
          <input className="input" value={form.summary} onChange={e => setF('summary', e.target.value)} />
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Обложка</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14 }}>
            Большая картинка, которая «прилипает» справа от текста, пока читаешь статью (как инфографика).
            Необязательно — без обложки текст просто займёт всю ширину.
          </p>
          <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
            <div style={{
              width: 160, height: 200, borderRadius: 10, background: '#f1f3f7', border: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
            }}>
              {form.cover_image
                ? <img src={form.cover_image} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : <span style={{ color: 'var(--muted)', fontSize: 12, textAlign: 'center', padding: 8 }}>нет обложки</span>}
            </div>
            <div>
              <input ref={el => (fileInputs.current.__cover = el)} type="file" accept="image/*" style={{ display: 'none' }}
                     onChange={e => { if (e.target.files[0]) uploadCover(e.target.files[0]); e.target.value = '' }} />
              <button className="btn btn-sm" disabled={uploadingSlot === coverSlot} onClick={() => fileInputs.current.__cover?.click()} style={{ marginRight: 8 }}>
                {uploadingSlot === coverSlot ? 'Загрузка…' : (form.cover_image ? 'Заменить' : '🖼️ Загрузить картинку')}
              </button>
              {form.cover_image && (
                <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => setF('cover_image', '')}>Убрать</button>
              )}
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8, maxWidth: 320 }}>
                Или впиши URL картинки вручную (например, если файл уже лежит в проекте):
              </p>
              <input className="input" style={{ marginTop: 6, fontSize: 12, maxWidth: 320 }} placeholder="/content/moya-kartinka.png"
                     value={form.cover_image} onChange={e => setF('cover_image', e.target.value)} />
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Содержание (JSON)</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10, whiteSpace: 'pre-wrap' }}>{BLOCKS_HELP}</p>
          <textarea className="input" rows={18} style={{ fontFamily: 'monospace', fontSize: 13 }}
                    value={blocksText} onChange={e => setBlocksText(e.target.value)} />
        </div>

        {imageSlots.length > 0 && (
          <div className="card" style={{ marginBottom: 20 }}>
            <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Картинки</h3>
            <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14 }}>
              То же самое можно сделать в Настройках → Фоны, слот с таким же именем.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {imageSlots.map(({ slot, caption }) => (
                <div key={slot} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{
                    width: 90, height: 60, borderRadius: 8, background: '#f1f3f7', border: '1px solid var(--border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
                  }}>
                    {settings?.[slot]
                      ? <img src={settings[slot]} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      : <span style={{ color: 'var(--muted)', fontSize: 10, textAlign: 'center' }}>нет</span>}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{caption || slot}</div>
                    <div style={{ fontSize: 11, color: 'var(--muted)' }}>{slot}</div>
                  </div>
                  <input ref={el => (fileInputs.current[slot] = el)} type="file" accept="image/*" style={{ display: 'none' }}
                         onChange={e => { if (e.target.files[0]) uploadSlot(slot, e.target.files[0]); e.target.value = '' }} />
                  <button className="btn btn-sm" disabled={uploadingSlot === slot} onClick={() => fileInputs.current[slot]?.click()}>
                    {uploadingSlot === slot ? 'Загрузка…' : (settings?.[slot] ? 'Заменить' : 'Загрузить')}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {jsonErr && <p style={{ color: 'var(--red)', marginBottom: 14 }}>{jsonErr}</p>}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', paddingBottom: 40 }}>
          {!isNew && <button className="btn" onClick={() => window.open(`/materials/article/${id}`, '_blank')}>👁 Посмотреть</button>}
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Сохраняю…' : '💾 Сохранить'}</button>
        </div>
      </div>
    </div>
  )
}
