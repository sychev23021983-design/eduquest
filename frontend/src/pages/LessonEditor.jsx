import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

const SUBJECTS = [
  { value: 'math',    label: '🔢 Математика' },
  { value: 'russian', label: '📝 Русский язык' },
  { value: 'science', label: '🌿 Окружающий мир' },
  { value: 'history', label: '🏛️ История' },
]

const EMPTY_Q = { text: '', options: ['', '', '', ''], correct: 0, hint: '', explanation: '' }

export default function LessonEditor() {
  const { id } = useParams()
  const { token } = useAuth()
  const nav = useNavigate()
  const isNew = !id

  const [saving,  setSaving]  = useState(false)
  const [msg,     setMsg]     = useState('')
  const [savedId, setSavedId] = useState(null)

  const [form, setForm] = useState({
    subject: 'math', grade: 4, topic: '', context_theme: 'minecraft',
    explanation: '', explanation_game: '',
    coins_lesson: 50, coins_boss: 30,
  })
  const [questions, setQuestions] = useState([{ ...EMPTY_Q }])
  const [boss, setBoss] = useState({ text: '', solution: '', hint1: '', hint2: '' })
  const [audioFile,  setAudioFile]  = useState(null)
  const [imageFile,  setImageFile]  = useState(null)
  const [audioPreview, setAudioPreview] = useState('')
  const [imagePreview, setImagePreview] = useState('')

  useEffect(() => {
    if (!isNew) loadLesson()
  }, [id])

  async function loadLesson() {
    const l = await api.lesson(token, id)
    setForm({
      subject: l.subject, grade: l.grade, topic: l.topic,
      context_theme: l.context_theme, explanation: l.explanation || '',
      explanation_game: l.explanation_game || '',
      coins_lesson: l.coins_lesson, coins_boss: l.coins_boss,
    })
    try { setQuestions(JSON.parse(l.questions || '[]') || [{ ...EMPTY_Q }]) } catch { }
    try { if (l.boss_task) setBoss(JSON.parse(l.boss_task)) } catch { }
    if (l.audio_file) setAudioPreview(l.audio_file)
    if (l.infographic) setImagePreview(l.infographic)
    setSavedId(Number(id))
  }

  function setF(key, val) { setForm(f => ({ ...f, [key]: val })) }

  function setQ(i, key, val) {
    setQuestions(qs => qs.map((q, idx) => idx === i ? { ...q, [key]: val } : q))
  }
  function setQOption(i, oi, val) {
    setQuestions(qs => qs.map((q, idx) => {
      if (idx !== i) return q
      const opts = [...q.options]; opts[oi] = val; return { ...q, options: opts }
    }))
  }
  function addQuestion() { setQuestions(qs => [...qs, { ...EMPTY_Q }]) }
  function removeQuestion(i) { setQuestions(qs => qs.filter((_, idx) => idx !== i)) }

  async function save() {
    if (!form.topic.trim()) { setMsg('Введите тему урока'); return }
    setSaving(true); setMsg('')
    try {
      const payload = {
        ...form,
        grade: Number(form.grade),
        coins_lesson: Number(form.coins_lesson),
        coins_boss: Number(form.coins_boss),
        questions: JSON.stringify(questions.filter(q => q.text.trim())),
        boss_task: boss.text.trim() ? JSON.stringify(boss) : null,
      }
      let lid = savedId
      if (isNew && !lid) {
        const res = await api.createLesson(token, payload)
        lid = res.id; setSavedId(lid)
      } else {
        await api.updateLesson(token, lid, payload)
      }
      // Upload files
      if (audioFile) {
        const fd = new FormData(); fd.append('file', audioFile)
        const r = await api.uploadAudio(token, lid, fd)
        setAudioPreview(r.audio_file); setAudioFile(null)
      }
      if (imageFile) {
        const fd = new FormData(); fd.append('file', imageFile)
        const r = await api.uploadImage(token, lid, fd)
        setImagePreview(r.infographic); setImageFile(null)
      }
      setMsg('✅ Сохранено!')
      setTimeout(() => nav('/parent'), 1200)
    } catch (e) { setMsg('Ошибка: ' + e.message) }
    finally { setSaving(false) }
  }

  const S = (label, children, hint) => (
    <div style={{ marginBottom: 20 }}>
      <label style={{ display: 'block', fontWeight: 600, marginBottom: 6, fontSize: 14 }}>{label}</label>
      {hint && <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>{hint}</div>}
      {children}
    </div>
  )

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#fff', borderBottom: '1px solid var(--border)', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14, position: 'sticky', top: 0, zIndex: 10 }}>
        <button onClick={() => nav('/parent')} style={{ background: 'none', border: 'none', fontSize: 20, color: 'var(--muted)' }}>‹</button>
        <h1 style={{ flex: 1, fontSize: 17, fontWeight: 600 }}>{isNew ? 'Новый урок' : 'Редактировать урок'}</h1>
        {msg && <span style={{ fontSize: 13, color: msg.startsWith('✅') ? 'var(--green)' : 'var(--red)' }}>{msg}</span>}
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Сохранение...' : '💾 Сохранить'}
        </button>
      </div>

      <div className="page" style={{ maxWidth: 760 }}>

        {/* Basic info */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 600, marginBottom: 16 }}>Основная информация</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {S('Предмет', (
              <select className="input" value={form.subject} onChange={e => setF('subject', e.target.value)}>
                {SUBJECTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            ))}
            {S('Класс', (
              <input className="input" type="number" min={1} max={11} value={form.grade}
                     onChange={e => setF('grade', e.target.value)} />
            ))}
          </div>
          {S('Тема урока', (
            <input className="input" placeholder="Например: Площадь прямоугольника" value={form.topic}
                   onChange={e => setF('topic', e.target.value)} />
          ))}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {S('Игровой контекст', (
              <input className="input" placeholder="minecraft / roblox / among_us" value={form.context_theme}
                     onChange={e => setF('context_theme', e.target.value)} />
            ))}
          </div>
        </div>

        {/* Explanations */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 600, marginBottom: 16 }}>Объяснение</h3>
          {S('Официальное объяснение', (
            <textarea className="input" rows={4} placeholder="Краткое объяснение темы (из промпта 1 NotebookLM)"
                      value={form.explanation} onChange={e => setF('explanation', e.target.value)} />
          ), 'Результат промпта 1 из шаблона NotebookLM')}
          {S('Игровое объяснение (Minecraft)', (
            <textarea className="input" rows={5} placeholder="История Стива, объясняющая тему (из промпта 2)"
                      value={form.explanation_game} onChange={e => setF('explanation_game', e.target.value)} />
          ), 'Результат промпта 2 — через контекст игры')}
        </div>

        {/* Media */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 600, marginBottom: 16 }}>Медиа</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div>
              <label style={{ display: 'block', fontWeight: 600, marginBottom: 6, fontSize: 14 }}>🎧 Аудио-файл</label>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>MP3 из Audio Overview NotebookLM</div>
              <input type="file" accept="audio/*" onChange={e => setAudioFile(e.target.files[0])}
                     style={{ fontSize: 13, marginBottom: 8 }} />
              {audioPreview && (
                <div style={{ background: 'var(--blue-light)', borderRadius: 8, padding: 10 }}>
                  <div style={{ fontSize: 12, color: 'var(--blue)', marginBottom: 6 }}>✅ Файл загружен</div>
                  <audio controls src={audioPreview} style={{ width: '100%' }} />
                </div>
              )}
            </div>
            <div>
              <label style={{ display: 'block', fontWeight: 600, marginBottom: 6, fontSize: 14 }}>🖼️ Инфографика</label>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>PNG/JPG из Canva или другого редактора</div>
              <input type="file" accept="image/*" onChange={e => setImageFile(e.target.files[0])}
                     style={{ fontSize: 13, marginBottom: 8 }} />
              {imagePreview && (
                <img src={imagePreview} alt="preview" style={{ width: '100%', borderRadius: 8, maxHeight: 120, objectFit: 'cover' }} />
              )}
            </div>
          </div>
        </div>

        {/* Questions */}
        <div className="card" style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ fontWeight: 600 }}>Вопросы ({questions.length})</h3>
            <button className="btn btn-sm" onClick={addQuestion}>+ Добавить вопрос</button>
          </div>
          {questions.map((q, i) => (
            <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 10, padding: 16, marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>Вопрос {i + 1}</span>
                {questions.length > 1 && (
                  <button onClick={() => removeQuestion(i)}
                          style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', fontSize: 16 }}>✕</button>
                )}
              </div>
              <textarea className="input" rows={2} placeholder="Текст вопроса (в контексте Minecraft/игры)"
                        value={q.text} onChange={e => setQ(i, 'text', e.target.value)}
                        style={{ marginBottom: 10 }} />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                {q.options.map((opt, oi) => (
                  <div key={oi} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <input type="radio" name={`correct_${i}`} checked={q.correct === oi}
                           onChange={() => setQ(i, 'correct', oi)} />
                    <input className="input" placeholder={`Вариант ${['А','Б','В','Г'][oi]}`}
                           value={opt} onChange={e => setQOption(i, oi, e.target.value)} style={{ flex: 1 }} />
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 12, color: 'var(--green)', marginBottom: 8 }}>
                ✅ Правильный: вариант {['А','Б','В','Г'][q.correct]} — выбери радиокнопку рядом с правильным ответом
              </div>
              <input className="input" placeholder="Подсказка (необязательно)" value={q.hint}
                     onChange={e => setQ(i, 'hint', e.target.value)} style={{ marginBottom: 8 }} />
              <input className="input" placeholder="Объяснение ответа (из промпта 3 NotebookLM)"
                     value={q.explanation} onChange={e => setQ(i, 'explanation', e.target.value)} />
            </div>
          ))}
        </div>

        {/* Boss task */}
        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 600, marginBottom: 16 }}>⚔️ Финальная задача (босс)</h3>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
            Результат промпта 4 из шаблона NotebookLM. Оставь пустым, если не нужно.
          </div>
          <textarea className="input" rows={4} placeholder="Условие задачи (из промпта 4)"
                    value={boss.text} onChange={e => setBoss(b => ({ ...b, text: e.target.value }))}
                    style={{ marginBottom: 10 }} />
          <textarea className="input" rows={3} placeholder="Решение по шагам (показывается после ответа)"
                    value={boss.solution} onChange={e => setBoss(b => ({ ...b, solution: e.target.value }))}
                    style={{ marginBottom: 10 }} />
          <input className="input" placeholder="Подсказка 1 (необязательно)"
                 value={boss.hint1} onChange={e => setBoss(b => ({ ...b, hint1: e.target.value }))}
                 style={{ marginBottom: 8 }} />
          <input className="input" placeholder="Подсказка 2 (необязательно)"
                 value={boss.hint2} onChange={e => setBoss(b => ({ ...b, hint2: e.target.value }))} />
        </div>

        {/* Coins */}
        <div className="card" style={{ marginBottom: 24 }}>
          <h3 style={{ fontWeight: 600, marginBottom: 16 }}>🪙 Награда монетами</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            {S('За прохождение урока', (
              <input className="input" type="number" min={10} max={500} value={form.coins_lesson}
                     onChange={e => setF('coins_lesson', e.target.value)} />
            ))}
            {S('За финальную задачу', (
              <input className="input" type="number" min={10} max={500} value={form.coins_boss}
                     onChange={e => setF('coins_boss', e.target.value)} />
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', paddingBottom: 40 }}>
          <button className="btn" onClick={() => nav('/parent')}>Отмена</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Сохранение...' : '💾 Сохранить урок'}
          </button>
        </div>
      </div>
    </div>
  )
}
