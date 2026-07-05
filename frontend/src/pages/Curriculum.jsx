import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

const SUBJECTS = [
  { value: 'math',    label: '🔢 Математика' },
  { value: 'russian', label: '📝 Русский язык' },
  { value: 'science', label: '🌿 Окружающий мир' },
  { value: 'history', label: '🏛️ История' },
]
const GRADES = Array.from({ length: 11 }, (_, i) => i + 1)

export default function Curriculum() {
  const { token } = useAuth()
  const nav = useNavigate()
  const [grade, setGrade]     = useState(5)
  const [subject, setSubject] = useState('math')
  const [tree, setTree]       = useState([])
  const [loading, setLoading] = useState(true)
  const [newSection, setNewSection] = useState('')
  const [newTopic, setNewTopic] = useState({}) // sectionId -> text
  const [editingSection, setEditingSection] = useState(null) // id
  const [editingTopic, setEditingTopic] = useState(null) // id
  const [editText, setEditText] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importMsg, setImportMsg] = useState('')
  const [importing, setImporting] = useState(false)
  const [introOpenFor, setIntroOpenFor] = useState(null) // sectionId
  const [introDrafts, setIntroDrafts] = useState({}) // sectionId -> текст
  const [introSaving, setIntroSaving] = useState(null)

  useEffect(() => { load() }, [grade, subject])

  async function load() {
    setLoading(true)
    const data = await api.curriculum(token, grade, subject)
    setTree(data.sections)
    setLoading(false)
  }

  async function addSection() {
    if (!newSection.trim()) return
    await api.createSection(token, { grade, subject, title: newSection.trim(), order_index: tree.length })
    setNewSection(''); load()
  }
  async function renameSection(s) {
    await api.updateSection(token, s.id, { grade, subject, title: editText.trim(), order_index: s.order_index, intro: s.intro })
    setEditingSection(null); load()
  }
  async function removeSection(s) {
    if (!confirm(`Удалить раздел «${s.title}» вместе со всеми темами?`)) return
    await api.deleteSection(token, s.id); load()
  }
  async function moveSection(s, dir) {
    const idx = tree.findIndex(x => x.id === s.id)
    const swapWith = tree[idx + dir]
    if (!swapWith) return
    await Promise.all([
      api.updateSection(token, s.id, { grade, subject, title: s.title, order_index: swapWith.order_index, intro: s.intro }),
      api.updateSection(token, swapWith.id, { grade, subject, title: swapWith.title, order_index: s.order_index, intro: swapWith.intro }),
    ])
    load()
  }
  async function saveIntro(s) {
    const text = introDrafts[s.id] !== undefined ? introDrafts[s.id] : (s.intro || '')
    setIntroSaving(s.id)
    await api.updateSection(token, s.id, { grade, subject, title: s.title, order_index: s.order_index, intro: text })
    setIntroSaving(null)
    load()
  }
  function toggleIntro(s) {
    setIntroOpenFor(cur => cur === s.id ? null : s.id)
    setIntroDrafts(d => d[s.id] !== undefined ? d : { ...d, [s.id]: s.intro || '' })
  }

  async function addTopic(section) {
    const text = (newTopic[section.id] || '').trim()
    if (!text) return
    await api.createTopic(token, { section_id: section.id, title: text, order_index: section.topics.length })
    setNewTopic(t => ({ ...t, [section.id]: '' })); load()
  }
  async function renameTopic(t) {
    await api.updateTopic(token, t.id, { section_id: t.section_id, title: editText.trim(), order_index: t.order_index })
    setEditingTopic(null); load()
  }
  async function removeTopic(t) {
    if (!confirm(`Удалить тему «${t.title}»?`)) return
    await api.deleteTopic(token, t.id); load()
  }
  async function moveTopic(section, t, dir) {
    const idx = section.topics.findIndex(x => x.id === t.id)
    const swapWith = section.topics[idx + dir]
    if (!swapWith) return
    await Promise.all([
      api.updateTopic(token, t.id, { section_id: t.section_id, title: t.title, order_index: swapWith.order_index }),
      api.updateTopic(token, swapWith.id, { section_id: swapWith.section_id, title: swapWith.title, order_index: t.order_index }),
    ])
    load()
  }

  async function runImport() {
    if (!importText.trim()) return
    setImporting(true); setImportMsg('')
    try {
      const res = await api.importCurriculum(token, { grade, subject, text: importText })
      setImportMsg(`✅ Найдено разделов: ${res.sections_found}. Новых разделов: ${res.sections_created}, новых тем: ${res.topics_created}.`)
      setImportText('')
      load()
    } catch (e) {
      setImportMsg('❌ ' + e.message)
    } finally { setImporting(false) }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav('/parent')} style={{ background: 'none', border: 'none', fontSize: 30, lineHeight: 1, color: '#aaa', padding: '6px 14px', margin: '-6px -14px -6px -6px', cursor: 'pointer', minWidth: 44, minHeight: 44 }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>📖 Программа предмета</span>
      </div>

      <div className="page-wide">
        <div className="card" style={{ marginBottom: 20, display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Класс</label>
            <select className="input" value={grade} onChange={e => setGrade(Number(e.target.value))} style={{ width: 100 }}>
              {GRADES.map(g => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Предмет</label>
            <select className="input" value={subject} onChange={e => setSubject(e.target.value)} style={{ width: 220 }}>
              {SUBJECTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
        </div>

        <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 18 }}>
          Добавь разделы и темы так, как они идут в учебнике министерства образования, и по желанию — «Введение»
          к разделу (зачем он нужен ребёнку). Уроки здесь не создаются вручную: попроси Claude сгенерировать
          урок для темы — он появится тут сам после деплоя, зная всю программу целиком, чтобы не повторяться.
        </p>

        {loading ? <p style={{ color: 'var(--muted)' }}>Загрузка…</p> : (
          <>
            {tree.map((s, si) => (
              <div key={s.id} className="card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <button className="btn btn-sm" disabled={si === 0} onClick={() => moveSection(s, -1)} style={{ padding: '2px 8px' }}>↑</button>
                    <button className="btn btn-sm" disabled={si === tree.length - 1} onClick={() => moveSection(s, 1)} style={{ padding: '2px 8px' }}>↓</button>
                  </div>
                  {editingSection === s.id ? (
                    <input className="input" value={editText} onChange={e => setEditText(e.target.value)}
                           onKeyDown={e => e.key === 'Enter' && renameSection(s)} autoFocus style={{ flex: 1, fontWeight: 700 }} />
                  ) : (
                    <h3 style={{ flex: 1, fontWeight: 700, fontSize: 17 }}>{si + 1}. {s.title}</h3>
                  )}
                  {editingSection === s.id ? (
                    <button className="btn btn-sm btn-primary" onClick={() => renameSection(s)}>✓</button>
                  ) : (
                    <button className="btn btn-sm" onClick={() => { setEditingSection(s.id); setEditText(s.title) }}>✏️</button>
                  )}
                  <button className="btn btn-sm btn-danger" onClick={() => removeSection(s)}>✕</button>
                </div>

                <div style={{ marginLeft: 34, marginBottom: 14 }}>
                  <button className="btn btn-sm" onClick={() => toggleIntro(s)}>
                    {s.intro ? '📘 Введение' : '📘 Добавить введение'} {introOpenFor === s.id ? '▲' : '▼'}
                  </button>
                  {introOpenFor === s.id && (
                    <div style={{ marginTop: 10, background: 'var(--blue-light)', borderRadius: 10, padding: 14 }}>
                      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                        Мотивационный текст «что это и зачем» — показывается ребёнку перед темами раздела.
                      </p>
                      <textarea className="input" rows={7}
                                placeholder="Например: зачем нужны натуральные числа, как без них не обойтись..."
                                value={introDrafts[s.id] !== undefined ? introDrafts[s.id] : (s.intro || '')}
                                onChange={e => setIntroDrafts(d => ({ ...d, [s.id]: e.target.value }))}
                                style={{ marginBottom: 10 }} />
                      <button className="btn btn-primary btn-sm" onClick={() => saveIntro(s)} disabled={introSaving === s.id}>
                        {introSaving === s.id ? 'Сохраняю…' : '💾 Сохранить введение'}
                      </button>
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginLeft: 34 }}>
                  {s.topics.map((t, ti) => (
                    <div key={t.id} style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg)', borderRadius: 8, padding: '8px 10px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <button className="btn btn-sm" disabled={ti === 0} onClick={() => moveTopic(s, t, -1)} style={{ padding: '0 6px', fontSize: 11 }}>↑</button>
                        <button className="btn btn-sm" disabled={ti === s.topics.length - 1} onClick={() => moveTopic(s, t, 1)} style={{ padding: '0 6px', fontSize: 11 }}>↓</button>
                      </div>
                      {editingTopic === t.id ? (
                        <input className="input" value={editText} onChange={e => setEditText(e.target.value)}
                               onKeyDown={e => e.key === 'Enter' && renameTopic(t)} autoFocus style={{ flex: 1 }} />
                      ) : (
                        <span style={{ flex: 1 }}>{ti + 1}. {t.title}</span>
                      )}
                      <span style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                        {t.lesson_count > 0 ? `📚 ${t.lesson_count}` : '🤖 ждёт урок'}
                      </span>
                      {editingTopic === t.id ? (
                        <button className="btn btn-sm btn-primary" onClick={() => renameTopic(t)}>✓</button>
                      ) : (
                        <button className="btn btn-sm" onClick={() => { setEditingTopic(t.id); setEditText(t.title) }}>✏️</button>
                      )}
                      {t.lessons && t.lessons.length > 0 && (
                        <>
                          <button className="btn btn-sm" onClick={() => window.open(`/lesson/${t.lessons[0].id}`, '_blank')}>
                            👁 Посмотреть
                          </button>
                          <button className="btn btn-sm" onClick={() => nav(`/parent/lesson/${t.lessons[0].id}/edit`)}>
                            ✏️ Изменить
                          </button>
                        </>
                      )}
                      <button className="btn btn-sm btn-danger" onClick={() => removeTopic(t)}>✕</button>
                    </div>
                  ))}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input className="input" placeholder="Новая тема..." value={newTopic[s.id] || ''}
                           onChange={e => setNewTopic(nt => ({ ...nt, [s.id]: e.target.value }))}
                           onKeyDown={e => e.key === 'Enter' && addTopic(s)} />
                    <button className="btn btn-sm" onClick={() => addTopic(s)}>+ Тема</button>
                  </div>
                </div>
              </div>
            ))}

            <div className="card" style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <input className="input" placeholder="Новый раздел (например: Натуральные числа)" value={newSection}
                     onChange={e => setNewSection(e.target.value)}
                     onKeyDown={e => e.key === 'Enter' && addSection()} />
              <button className="btn btn-primary" onClick={addSection}>+ Раздел</button>
            </div>

            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                   onClick={() => setImportOpen(o => !o)}>
                <h3 style={{ fontWeight: 600, fontSize: 15 }}>📥 Импорт разделов и тем из текста</h3>
                <span style={{ color: 'var(--blue)' }}>{importOpen ? '▲' : '▼'}</span>
              </div>
              {importOpen && (
                <div style={{ marginTop: 14 }}>
                  <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 10 }}>
                    Вставь текст программы из учебника в формате: <code>**1. Раздел**</code> и ниже пункты{' '}
                    <code>- **Тема:** описание</code>. Повторный импорт безопасен — уже добавленные разделы и темы не дублируются.
                  </p>
                  <textarea className="input" rows={8} placeholder={'**1. Натуральные числа**\n\n- **Цифры и натуральные числа:** чтение и запись чисел...'}
                            value={importText} onChange={e => setImportText(e.target.value)} style={{ marginBottom: 10 }} />
                  {importMsg && <p style={{ fontSize: 13, marginBottom: 10, color: importMsg.startsWith('✅') ? 'var(--green)' : 'var(--red)' }}>{importMsg}</p>}
                  <button className="btn btn-primary" onClick={runImport} disabled={importing}>
                    {importing ? 'Импортирую…' : `Импортировать в ${SUBJECTS.find(s => s.value === subject)?.label}, ${grade} класс`}
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
