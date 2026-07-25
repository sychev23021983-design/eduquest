import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useLocation, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'

export default function SkillEditor() {
  const { id } = useParams()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const isCreateRoute = location.pathname === '/parent/skills/new'
  const mode = id ? 'edit' : (isCreateRoute ? 'create' : 'list') // 'list' | 'create' | 'edit'

  const { token } = useAuth()
  const { settings, refresh: reloadSettings } = useSettings()
  const nav = useNavigate()
  const fileInputs = useRef({})

  const [categories, setCategories] = useState([])
  const [skillsByCategory, setSkillsByCategory] = useState({})
  const [deletedCategories, setDeletedCategories] = useState([])
  const [deletedSkills, setDeletedSkills] = useState([])
  const [showDeleted, setShowDeleted] = useState(false)
  const [openGroups, setOpenGroups] = useState(new Set())
  const [newCategoryTitle, setNewCategoryTitle] = useState('')
  const [renamingId, setRenamingId] = useState(null)
  const [renameValue, setRenameValue] = useState('')

  const [form, setForm] = useState({ category_id: '', hint1: '', hint2: '', hint3: '', answer: '', image_url: '' })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [uploadingSlot, setUploadingSlot] = useState(null)
  const [createdId, setCreatedId] = useState(null)

  const effectiveId = id || createdId

  useEffect(() => {
    if (mode === 'list') loadList()
    else if (mode === 'edit') loadSkill()
    else initCreate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, id, location.search])

  function toggleGroup(key) {
    setOpenGroups(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  async function loadList() {
    const cats = await api.skillCategories(token)
    setCategories(cats)
    const entries = await Promise.all(cats.map(async c => [c.id, await api.skills(token, c.id)]))
    setSkillsByCategory(Object.fromEntries(entries))
    api.deletedSkillCategories(token).then(setDeletedCategories).catch(() => setDeletedCategories([]))
    api.deletedSkills(token).then(setDeletedSkills).catch(() => setDeletedSkills([]))
  }

  async function loadSkill() {
    const [s, cats] = await Promise.all([api.skill(token, id), api.skillCategories(token)])
    setCategories(cats)
    setForm({
      category_id: s.category_id, hint1: s.hint1 || '', hint2: s.hint2 || '', hint3: s.hint3 || '',
      answer: s.answer || '', image_url: s.image_url || '',
    })
  }

  async function initCreate() {
    const cats = await api.skillCategories(token)
    setCategories(cats)
    const qsCategory = Number(searchParams.get('category_id'))
    const category_id = cats.some(c => c.id === qsCategory) ? qsCategory : (cats[0]?.id || '')
    setForm({ category_id, hint1: '', hint2: '', hint3: '', answer: '', image_url: '' })
    setCreatedId(null)
    newSlotId.current = Math.random().toString(36).slice(2, 10)
  }

  function setF(key, val) { setForm(f => ({ ...f, [key]: val })) }

  const newSlotId = useRef(Math.random().toString(36).slice(2, 10))
  const imageSlot = effectiveId ? `skill_image_${effectiveId}` : `skill_image_new_${newSlotId.current}`

  async function uploadImage(file) {
    setUploadingSlot(imageSlot)
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await api.uploadSettingAsset(token, imageSlot, fd)
      const newUrl = res[imageSlot]
      setF('image_url', newUrl)
      await reloadSettings?.()
      if (effectiveId) {
        await api.updateSkill(token, effectiveId, {
          category_id: Number(form.category_id), image_url: newUrl,
          hint1: form.hint1 || null, hint2: form.hint2 || null, hint3: form.hint3 || null,
          answer: form.answer || null,
        })
        setMsg('✅ Картинка загружена и сохранена')
      } else {
        setMsg('✅ Картинка загружена (сохранится вместе с заданием по кнопке ниже)')
      }
    } catch (e) { setMsg('❌ ' + e.message) }
    setUploadingSlot(null)
    setTimeout(() => setMsg(''), 2500)
  }

  async function addCategory() {
    const title = newCategoryTitle.trim()
    if (!title) return
    await api.createSkillCategory(token, { title })
    setNewCategoryTitle('')
    loadList()
  }

  function startRename(cat) { setRenamingId(cat.id); setRenameValue(cat.title) }

  async function saveRename(catId) {
    const title = renameValue.trim()
    if (title) await api.updateSkillCategory(token, catId, { title })
    setRenamingId(null)
    loadList()
  }

  async function removeCategory(catId) {
    if (!confirm('Удалить категорию? Задания внутри тоже перестанут быть видны ребёнку, но не удалятся — их можно будет найти, восстановив категорию.')) return
    await api.deleteSkillCategory(token, catId)
    loadList()
  }

  async function restoreCategory(catId) {
    await api.restoreSkillCategory(token, catId)
    loadList()
  }

  async function save() {
    if (!form.category_id) { setMsg('❌ Выбери категорию.'); return }
    setSaving(true)
    try {
      const payload = {
        category_id: Number(form.category_id), image_url: form.image_url || null,
        hint1: form.hint1 || null, hint2: form.hint2 || null, hint3: form.hint3 || null,
        answer: form.answer || null,
      }
      if (effectiveId) {
        await api.updateSkill(token, effectiveId, payload)
        setMsg('✅ Сохранено')
      } else {
        const res = await api.createSkill(token, payload)
        setCreatedId(res.id)
        setMsg('✅ Задание создано')
      }
    } catch (e) { setMsg('❌ ' + e.message) }
    setSaving(false)
    setTimeout(() => setMsg(''), 4000)
  }

  function createAnother() {
    const category_id = form.category_id
    setForm({ category_id, hint1: '', hint2: '', hint3: '', answer: '', image_url: '' })
    setCreatedId(null)
    newSlotId.current = Math.random().toString(36).slice(2, 10)
    setMsg('')
  }

  async function removeSkill(skillId) {
    if (!confirm('Удалить задание?')) return
    await api.deleteSkill(token, skillId)
    loadList()
  }

  async function restoreSkill(skillId) {
    await api.restoreSkill(token, skillId)
    loadList()
  }

  const totalSkills = useMemo(
    () => Object.values(skillsByCategory).reduce((sum, arr) => sum + arr.length, 0),
    [skillsByCategory]
  )

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav(mode === 'list' ? '/parent' : '/parent/skills')} style={{ background: 'none', border: 'none', fontSize: 30, lineHeight: 1, color: '#aaa', padding: '6px 14px', margin: '-6px -14px -6px -6px', cursor: 'pointer', minWidth: 44, minHeight: 44 }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>🧠 Навыки</span>
        {msg && <span style={{ marginLeft: 'auto', color: msg.startsWith('✅') ? '#4ade80' : '#f87171', fontSize: 13 }}>{msg}</span>}
      </div>

      <div className="page-wide">

        {mode === 'list' && (
          <>
            <p style={{ fontSize: 13, color: 'var(--muted)', margin: '8px 0 18px' }}>
              Ребёнок видит картинку и рассуждает логически; если трудно — может открыть до трёх подсказок
              по очереди. Создай категории (например «Логика», «Исследование», «Проект») и добавь в каждую
              сколько угодно заданий.
            </p>

            <div className="card" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 20 }}>
              <input
                className="input" placeholder="Название новой категории, например «Логика»"
                value={newCategoryTitle} onChange={e => setNewCategoryTitle(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') addCategory() }}
              />
              <button className="btn btn-primary" onClick={addCategory}>+ Добавить категорию</button>
            </div>

            <h3 style={{ fontWeight: 600, paddingTop: 4, marginBottom: 12 }}>Все категории ({categories.length}), заданий всего: {totalSkills}</h3>

            {categories.length === 0 && (
              <div className="card gh-empty" style={{ textAlign: 'center', color: 'var(--muted)', marginBottom: 20 }}>
                Пока нет ни одной категории — добавь первую выше.
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
              {categories.map(c => {
                const isOpen = openGroups.has(c.id)
                const items = skillsByCategory[c.id] || []
                return (
                  <div key={c.id} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px' }}>
                      {renamingId === c.id ? (
                        <div style={{ display: 'flex', gap: 8, flex: 1, alignItems: 'center' }}>
                          <input className="input" value={renameValue} onChange={e => setRenameValue(e.target.value)}
                                 onKeyDown={e => { if (e.key === 'Enter') saveRename(c.id) }} autoFocus />
                          <button className="btn btn-sm" onClick={() => saveRename(c.id)}>💾</button>
                          <button className="btn btn-sm" onClick={() => setRenamingId(null)}>✕</button>
                        </div>
                      ) : (
                        <div
                          onClick={() => toggleGroup(c.id)}
                          style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, cursor: 'pointer' }}
                        >
                          <span style={{ fontWeight: 700 }}>{c.title}</span>
                          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                            {items.length} {items.length === 1 ? 'задание' : 'заданий'}
                          </span>
                          <span style={{ transition: 'transform .15s', transform: isOpen ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--muted)' }}>▾</span>
                        </div>
                      )}
                      {renamingId !== c.id && (
                        <>
                          <button className="btn btn-sm" onClick={() => startRename(c)} title="Переименовать">✏️</button>
                          <button className="btn btn-sm" onClick={() => nav(`/parent/skills/new?category_id=${c.id}`)} title="Добавить задание в эту категорию">
                            + Задание
                          </button>
                          <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => removeCategory(c.id)}>🗑️</button>
                        </>
                      )}
                    </div>
                    {isOpen && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 16px 16px' }}>
                        {items.length === 0 && (
                          <div style={{ fontSize: 13, color: 'var(--muted)', padding: '4px 0 8px' }}>Пока нет заданий в этой категории.</div>
                        )}
                        {items.map(s => (
                          <div key={s.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <div style={{
                              width: 56, height: 56, borderRadius: 8, background: '#f1f3f7', border: '1px solid var(--border)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
                            }}>
                              {s.image_url
                                ? <img src={s.image_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                                : <span style={{ color: 'var(--muted)', fontSize: 10 }}>нет</span>}
                            </div>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontWeight: 500 }}>Задание #{s.id}</div>
                              <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
                                Подсказок: {[s.hint1, s.hint2, s.hint3].filter(Boolean).length} / 3
                                {' · '}Ответ: {s.answer ? 'есть' : 'нет'}
                              </div>
                            </div>
                            <button className="btn btn-sm" onClick={() => window.open(`/skills/task/${s.id}`, '_blank')}>👁 Посмотреть</button>
                            <button className="btn btn-sm" onClick={() => nav(`/parent/skills/${s.id}/edit`)}>✏️ Изменить</button>
                            <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => removeSkill(s.id)}>🗑️</button>
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
                <span style={{ fontWeight: 700, flex: 1 }}>Удалённые категории и задания</span>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  {deletedCategories.length + deletedSkills.length}
                </span>
                <span style={{ transition: 'transform .15s', transform: showDeleted ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--muted)' }}>▾</span>
              </div>
              {showDeleted && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '0 16px 16px' }}>
                  {deletedCategories.length === 0 && deletedSkills.length === 0 && (
                    <div style={{ fontSize: 13, color: 'var(--muted)', padding: '4px 0 8px' }}>Пусто — ничего не удалено.</div>
                  )}
                  {deletedCategories.map(c => (
                    <div key={`cat-${c.id}`} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <span className="badge">категория</span>
                        <div style={{ fontWeight: 500, marginTop: 2 }}>{c.title} <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(id {c.id})</span></div>
                      </div>
                      <button className="btn btn-sm" onClick={() => restoreCategory(c.id)}>♻️ Восстановить</button>
                    </div>
                  ))}
                  {deletedSkills.map(s => (
                    <div key={`sk-${s.id}`} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <span className="badge">задание</span>
                        <div style={{ fontWeight: 500, marginTop: 2 }}>
                          {s.category_title || '—'} · #{s.id}
                        </div>
                      </div>
                      <button className="btn btn-sm" onClick={() => restoreSkill(s.id)}>♻️ Восстановить</button>
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
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Категория</label>
              <select className="input" value={form.category_id} onChange={e => setF('category_id', e.target.value)} style={{ marginBottom: 4 }}>
                {categories.length === 0 && <option value="">— нет категорий —</option>}
                {categories.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
              {categories.length === 0 && (
                <p style={{ fontSize: 12, color: 'var(--red)', marginTop: 6 }}>
                  Сначала создай хотя бы одну категорию в списке заданий.
                </p>
              )}
            </div>

            <div className="card" style={{ marginBottom: 20 }}>
              <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Картинка задания</h3>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14 }}>
                То, что увидит ребёнок на слайде — фото/картинка с задачей для логического рассуждения.
              </p>
              <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
                <div style={{
                  width: 220, height: 160, borderRadius: 10, background: '#f1f3f7', border: '1px solid var(--border)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
                }}>
                  {form.image_url
                    ? <img src={form.image_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                    : <span style={{ color: 'var(--muted)', fontSize: 12, textAlign: 'center', padding: 8 }}>нет картинки</span>}
                </div>
                <div>
                  <input ref={el => (fileInputs.current.__image = el)} type="file" accept="image/*" style={{ display: 'none' }}
                         onChange={e => { if (e.target.files[0]) uploadImage(e.target.files[0]); e.target.value = '' }} />
                  <button className="btn btn-sm" disabled={uploadingSlot === imageSlot} onClick={() => fileInputs.current.__image?.click()} style={{ marginRight: 8 }}>
                    {uploadingSlot === imageSlot ? 'Загрузка…' : (form.image_url ? 'Заменить' : '🖼️ Загрузить картинку')}
                  </button>
                  {form.image_url && (
                    <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={() => setF('image_url', '')}>Убрать</button>
                  )}
                </div>
              </div>
            </div>

            <div className="card" style={{ marginBottom: 20 }}>
              <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Подсказки (до 3, необязательно)</h3>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14 }}>
                Ребёнок сможет открыть их по одной, если задание покажется трудным.
              </p>
              {[1, 2, 3].map(n => (
                <div key={n} style={{ marginBottom: 12 }}>
                  <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Подсказка {n}</label>
                  <textarea className="input" rows={2} value={form[`hint${n}`]} onChange={e => setF(`hint${n}`, e.target.value)} />
                </div>
              ))}
            </div>

            <div className="card" style={{ marginBottom: 20 }}>
              <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Правильный ответ (необязательно)</h3>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14 }}>
                Ребёнок увидит это описание решения только после того, как откроет все подсказки и нажмёт
                кнопку «Сдаюсь».
              </p>
              <textarea className="input" rows={3} value={form.answer} onChange={e => setF('answer', e.target.value)} />
            </div>

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', marginBottom: 40, flexWrap: 'wrap' }}>
              {effectiveId && <button className="btn" onClick={() => window.open(`/skills/task/${effectiveId}`, '_blank')}>👁 Посмотреть</button>}
              {mode === 'create' && createdId && (
                <button className="btn" onClick={createAnother}>+ Создать ещё одно задание в этой категории</button>
              )}
              <button className="btn btn-primary" onClick={save} disabled={saving || categories.length === 0}>{saving ? 'Сохраняю…' : '💾 Сохранить'}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
