import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useLocation, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ, MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import { SendAssignmentPanel, AssignmentHistory } from '../components/MaterialAssignmentTools.jsx'

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

const DEFAULT_SUBJECT = 'biology'

export default function ArticleEditor() {
  const { id } = useParams()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const isCreateRoute = location.pathname === '/parent/materials/new'
  const mode = id ? 'edit' : (isCreateRoute ? 'create' : 'list') // 'list' | 'create' | 'edit'

  const { token } = useAuth()
  const { settings, refresh: reloadSettings } = useSettings()
  const nav = useNavigate()
  const fileInputs = useRef({})

  const [list, setList] = useState([])
  const [deletedList, setDeletedList] = useState([])
  const [showDeleted, setShowDeleted] = useState(false)
  const [form, setForm] = useState({ subject: DEFAULT_SUBJECT, grade: 5, title: '', summary: '', cover_image: '' })
  const [blocksText, setBlocksText] = useState(emptyBlocksText)
  const [jsonErr, setJsonErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [uploadingSlot, setUploadingSlot] = useState(null)
  const [openGroups, setOpenGroups] = useState(new Set())
  const [createdId, setCreatedId] = useState(null) // id материала, только что созданного в этой сессии редактора
  const [historyKey, setHistoryKey] = useState(0) // инкремент триггерит обновление истории отправок
  // Блок «Содержание (JSON)» свёрнут по умолчанию и перенесён в самый низ, под кнопки —
  // чтобы кнопки «Сохранить»/«Просмотреть» были сразу видны под Обложкой, без прокрутки
  // мимо большого JSON-редактора. Автоматически раскрывается, если в JSON ошибка.
  const [blocksOpen, setBlocksOpen] = useState(false)

  const effectiveId = id || createdId

  function toggleGroup(key) {
    setOpenGroups(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  const [search, setSearch] = useState('')

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filteredList = q ? list.filter(a => a.title.toLowerCase().includes(q)) : list
    const bySubject = {}
    for (const a of filteredList) {
      (bySubject[a.subject] = bySubject[a.subject] || []).push(a)
    }
    if (q) {
      // при поиске показываем только категории, где есть совпадения
      return Object.keys(MATERIAL_SUBJ).filter(k => bySubject[k]?.length).map(k => ({ key: k, items: bySubject[k] }))
    }
    return Object.keys(MATERIAL_SUBJ).map(k => ({ key: k, items: bySubject[k] || [] }))
  }, [list, search])

  const filteredDeleted = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? deletedList.filter(a => a.title.toLowerCase().includes(q)) : deletedList
  }, [deletedList, search])

  useEffect(() => {
    if (mode === 'list') loadList()
    else if (mode === 'edit') loadArticle()
    else initCreate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, id, location.search])

  async function loadList() {
    const all = await Promise.all(Object.keys(MATERIAL_SUBJ).map(s => api.articles(token, s)))
    setList(all.flat())
    api.deletedArticles(token).then(setDeletedList).catch(() => setDeletedList([]))
  }

  async function loadArticle() {
    const a = await api.article(token, id)
    setForm({ subject: a.subject, grade: a.grade || 5, title: a.title, summary: a.summary || '', cover_image: a.cover_image || '' })
    setBlocksText(JSON.stringify(a.blocks, null, 2))
  }

  function initCreate() {
    const qsSubject = searchParams.get('subject')
    const subject = (qsSubject && MATERIAL_SUBJ[qsSubject]) ? qsSubject : DEFAULT_SUBJECT
    setForm({ subject, grade: 5, title: '', summary: '', cover_image: '' })
    setBlocksText(emptyBlocksText)
    setCreatedId(null)
    setJsonErr('')
    // Важно: сбрасываем временное имя слота обложки. Раньше это делал только createAnother(),
    // а не initCreate() — если переход между разными категориями («+ Материал») происходил без
    // полного перемонтирования компонента (тот же путь /parent/materials/new, разный ?subject=),
    // старое временное имя слота оставалось прежним, и загрузка обложки для новой статьи могла
    // перезаписать файл, который уже использовался в другой, ещё не сохранённой сессии создания.
    newSlotId.current = Math.random().toString(36).slice(2, 10)
  }

  function setF(key, val) { setForm(f => ({ ...f, [key]: val })) }

  const newSlotId = useRef(Math.random().toString(36).slice(2, 10))
  const coverSlot = effectiveId ? `article_cover_${effectiveId}` : `article_cover_new_${newSlotId.current}`

  async function uploadCover(file) {
    setUploadingSlot(coverSlot)
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await api.uploadSettingAsset(token, coverSlot, fd)
      const newCover = res[coverSlot]
      setF('cover_image', newCover)
      await reloadSettings?.()
      if (effectiveId) {
        // Сразу сохраняем обложку в самой статье — иначе она хранится только в настройках-слоте
        // и «слетает» при перезагрузке страницы до нажатия кнопки «Сохранить».
        const blocks = parsedBlocks() || []
        await api.updateArticle(token, effectiveId, {
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

  // Группирует блоки в слайды так же, как это делает страница чтения (ArticlePage.jsx):
  // каждый heading начинает новый слайд.
  function groupIntoSlides(blocks) {
    const slides = []
    let cur = null
    for (const b of blocks) {
      if (b.type === 'heading') { cur = [b]; slides.push(cur) }
      else { if (!cur) { cur = []; slides.push(cur) }; cur.push(b) }
    }
    return slides
  }

  function dedupeSlides() {
    const blocks = parsedBlocks()
    if (!Array.isArray(blocks)) { setJsonErr('Ошибка в JSON блоков — проверь синтаксис.'); return }
    setJsonErr('')
    const slides = groupIntoSlides(blocks)
    const seen = new Set()
    const kept = []
    let removed = 0
    for (const slide of slides) {
      const key = JSON.stringify(slide)
      if (seen.has(key)) { removed++; continue }
      seen.add(key)
      kept.push(slide)
    }
    if (removed === 0) {
      setMsg('✅ Повторяющихся слайдов не найдено')
    } else {
      setBlocksText(JSON.stringify(kept.flat(), null, 2))
      setMsg(`✅ Убрано ${removed} повторяющихся слайдов из ${slides.length} — не забудь нажать «Сохранить»`)
    }
    setTimeout(() => setMsg(''), 5000)
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
    if (!blocks) { setJsonErr('Ошибка в JSON блоков — проверь синтаксис.'); setBlocksOpen(true); return }
    if (!form.title.trim()) { setJsonErr('Укажи заголовок материала.'); return }
    setSaving(true)
    try {
      const payload = { subject: form.subject, grade: Number(form.grade) || null, title: form.title.trim(), summary: form.summary, cover_image: form.cover_image || null, blocks }
      if (effectiveId) {
        await api.updateArticle(token, effectiveId, payload)
        setMsg('✅ Сохранено')
      } else {
        const res = await api.createArticle(token, payload)
        setCreatedId(res.id)
        setMsg('✅ Материал создан')
      }
    } catch (e) { setMsg('❌ ' + e.message) }
    setSaving(false)
    setTimeout(() => setMsg(''), 4000)
  }

  function createAnother() {
    const subject = form.subject
    setForm({ subject, grade: 5, title: '', summary: '', cover_image: '' })
    setBlocksText(emptyBlocksText)
    setCreatedId(null)
    newSlotId.current = Math.random().toString(36).slice(2, 10)
    setJsonErr('')
    setMsg('')
  }

  async function remove(articleId) {
    if (!confirm('Удалить материал?')) return
    await api.deleteArticle(token, articleId)
    loadList()
  }

  async function restore(articleId) {
    await api.restoreArticle(token, articleId)
    loadList()
  }

  async function purge(articleId) {
    if (!confirm('Убрать безвозвратно? Это нельзя отменить.')) return
    await api.purgeArticle(token, articleId)
    loadList()
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav(mode === 'list' ? '/parent' : '/parent/materials')} style={{ background: 'none', border: 'none', fontSize: 30, lineHeight: 1, color: '#aaa', padding: '6px 14px', margin: '-6px -14px -6px -6px', cursor: 'pointer', minWidth: 44, minHeight: 44 }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>📚 Познавательные материалы</span>
        {msg && <span style={{ marginLeft: 'auto', color: msg.startsWith('✅') ? '#4ade80' : '#f87171', fontSize: 13 }}>{msg}</span>}
      </div>

      <div className="page-wide">

        {mode === 'list' && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
              <h3 style={{ fontWeight: 600, paddingTop: 8 }}>Все материалы ({list.length})</h3>
              <SendAssignmentPanel token={token} onSent={() => setHistoryKey(k => k + 1)} />
            </div>
            <AssignmentHistory token={token} refreshKey={historyKey} />
            <input
              className="input" placeholder="🔍 Поиск по названию — во всех категориях сразу, включая удалённые"
              value={search} onChange={e => setSearch(e.target.value)}
              style={{ marginBottom: 16 }}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
              {groups.map(g => {
                const isOpen = search.trim() ? true : openGroups.has(g.key)
                return (
                  <div key={g.key} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px' }}>
                      <div
                        onClick={() => toggleGroup(g.key)}
                        style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, cursor: 'pointer' }}
                      >
                        <span style={{ fontSize: 20 }}>{MATERIAL_SUBJ_ICON[g.key]}</span>
                        <span style={{ fontWeight: 700 }}>{MATERIAL_SUBJ[g.key]}</span>
                        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                          {g.items.length} {g.items.length === 1 ? 'материал' : 'материалов'}
                        </span>
                        <span style={{ transition: 'transform .15s', transform: isOpen ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--muted)' }}>▾</span>
                      </div>
                      <button className="btn btn-sm" onClick={() => nav(`/parent/materials/new?subject=${g.key}`)} title="Добавить материал в эту категорию">
                        + Материал
                      </button>
                    </div>
                    {isOpen && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 16px 16px' }}>
                        {g.items.length === 0 && (
                          <div style={{ fontSize: 13, color: 'var(--muted)', padding: '4px 0 8px' }}>Пока нет материалов в этой категории.</div>
                        )}
                        {g.items.map(a => (
                          <div key={a.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontWeight: 500 }}>{a.title} <span style={{ color: 'var(--muted)', fontWeight: 400, fontSize: 12 }}>(id {a.id})</span></div>
                              {a.summary && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{a.summary}</div>}
                            </div>
                            <button className="btn btn-sm" onClick={() => window.open(`/materials/article/${a.id}`, '_blank')}>👁 Посмотреть</button>
                            <button className="btn btn-sm" onClick={() => nav(`/parent/materials/${a.id}/edit`)}>✏️ Изменить</button>
                            <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => remove(a.id)}>🗑️</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 28 }}>
              <div
                onClick={() => setShowDeleted(v => !v)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', cursor: 'pointer' }}
              >
                <span style={{ fontSize: 20 }}>🗑</span>
                <span style={{ fontWeight: 700, flex: 1 }}>Удалённые материалы</span>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  {filteredDeleted.length} {filteredDeleted.length === 1 ? 'штука' : 'штук'}
                </span>
                <span style={{ transition: 'transform .15s', transform: (showDeleted || search.trim()) ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--muted)' }}>▾</span>
              </div>
              {(showDeleted || search.trim()) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 16px 16px' }}>
                  <p style={{ fontSize: 12, color: 'var(--muted)', margin: '0 0 4px' }}>
                    Здесь оказываются материалы после нажатия «🗑️» в списке выше — они помечаются
                    удалёнными, но не стираются из базы сразу. Если материал всё равно где-то
                    показывается (например, в слайд-шоу), проверь здесь — если он есть в этом
                    списке, значит удаление сработало и это какая-то другая запись; если его тут
                    нет вообще, значит он до сих пор активен.
                  </p>
                  {filteredDeleted.length === 0 && (
                    <div style={{ fontSize: 13, color: 'var(--muted)', padding: '4px 0 8px' }}>Пусто — ничего не удалено.</div>
                  )}
                  {filteredDeleted.map(a => (
                    <div key={a.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <span className="badge">{MATERIAL_SUBJ[a.subject] || a.subject}</span>
                        <div style={{ fontWeight: 500, marginTop: 2 }}>{a.title} <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(id {a.id})</span></div>
                        {a.summary && <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{a.summary}</div>}
                      </div>
                      <button className="btn btn-sm" onClick={() => restore(a.id)}>♻️ Восстановить</button>
                      <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => purge(a.id)}>🗑️ Убрать навсегда</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {mode !== 'list' && (
          <>
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

            {jsonErr && <p style={{ color: 'var(--red)', marginBottom: 14 }}>{jsonErr}</p>}

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginBottom: 20, flexWrap: 'wrap' }}>
              {effectiveId && <button className="btn" onClick={() => window.open(`/materials/article/${effectiveId}`, '_blank')}>👁 Посмотреть</button>}
              {mode === 'create' && createdId && (
                <button className="btn" onClick={createAnother}>+ Создать ещё один материал в этой категории</button>
              )}
              <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Сохраняю…' : '💾 Сохранить'}</button>
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

            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div
                onClick={() => setBlocksOpen(v => !v)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', cursor: 'pointer' }}
              >
                <span style={{ fontWeight: 700, flex: 1 }}>Содержание (JSON)</span>
                <span style={{ transition: 'transform .15s', transform: blocksOpen ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--muted)' }}>▾</span>
              </div>
              {blocksOpen && (
                <div style={{ padding: '0 16px 16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
                    <button className="btn btn-sm" onClick={dedupeSlides} title="Найти и убрать слайды, которые полностью повторяют предыдущие">
                      🧹 Убрать повторяющиеся слайды
                    </button>
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10, whiteSpace: 'pre-wrap' }}>{BLOCKS_HELP}</p>
                  <textarea className="input" rows={18} style={{ fontFamily: 'monospace', fontSize: 13 }}
                            value={blocksText} onChange={e => setBlocksText(e.target.value)} />
                </div>
              )}
            </div>
            <div style={{ paddingBottom: 40 }} />
          </>
        )}
      </div>
    </div>
  )
}
