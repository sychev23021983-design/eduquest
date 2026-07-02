import { useEffect, useState, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

export default function LessonEditor() {
  const { id } = useParams()
  const { token } = useAuth()
  const nav = useNavigate()
  const imgInput = useRef(null)
  const audioInput = useRef(null)

  const [lesson, setLesson] = useState(null)
  const [form, setForm] = useState(null)
  const [questionsText, setQuestionsText] = useState('')
  const [bossText, setBossText] = useState('')
  const [jsonErr, setJsonErr] = useState('')
  const [uploading, setUploading] = useState(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { load() }, [id])

  async function load() {
    const l = await api.lesson(token, id)
    setLesson(l)
    setForm({
      topic: l.topic, context_theme: l.context_theme,
      explanation_game: l.explanation_game || '', explanation: l.explanation || '',
      coins_lesson: l.coins_lesson, coins_boss: l.coins_boss,
    })
    setQuestionsText(JSON.stringify(JSON.parse(l.questions || '[]'), null, 2))
    setBossText(l.boss_task ? JSON.stringify(JSON.parse(l.boss_task), null, 2) : '')
  }

  function setF(key, val) { setForm(f => ({ ...f, [key]: val })) }

  function lessonPayload(overrideLesson) {
    const L = overrideLesson || lesson
    return {
      subject: L.subject, grade: L.grade, topic: form.topic, topic_id: L.topic_id,
      context_theme: form.context_theme, explanation: form.explanation, explanation_game: form.explanation_game,
      questions: questionsText, boss_task: bossText.trim() || null,
      coins_lesson: Number(form.coins_lesson), coins_boss: Number(form.coins_boss),
    }
  }

  async function uploadImage(file) {
    setUploading('image')
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await api.uploadImage(token, id, fd)
      setLesson(l => ({ ...l, infographic: res.infographic }))
      setMsg('✅ Картинка загружена')
    } catch (e) { setMsg('❌ ' + e.message) }
    setUploading(null)
    setTimeout(() => setMsg(''), 2500)
  }

  async function removeImage() {
    if (!confirm('Убрать картинку и вернуть текстовое описание?')) return
    try {
      await api.clearInfographic(token, id)
      setLesson(l => ({ ...l, infographic: null }))
      setMsg('✅ Картинка убрана')
    } catch (e) { setMsg('❌ ' + e.message) }
    setTimeout(() => setMsg(''), 2500)
  }

  async function uploadAudio(file) {
    setUploading('audio')
    try {
      const fd = new FormData(); fd.append('file', file)
      const res = await api.uploadAudio(token, id, fd)
      setLesson(l => ({ ...l, audio_file: res.audio_file }))
      setMsg('✅ Аудио загружено')
    } catch (e) { setMsg('❌ ' + e.message) }
    setUploading(null)
    setTimeout(() => setMsg(''), 2500)
  }

  async function save() {
    setJsonErr('')
    try {
      JSON.parse(questionsText)
      if (bossText.trim()) JSON.parse(bossText)
    } catch (e) {
      setJsonErr('Ошибка в JSON вопросов или финального задания: ' + e.message)
      return
    }
    setSaving(true)
    try {
      await api.updateLesson(token, id, lessonPayload())
      setMsg('✅ Сохранено')
    } catch (e) { setMsg('❌ ' + e.message) }
    setSaving(false)
    setTimeout(() => setMsg(''), 2500)
  }

  if (!form || !lesson) return <div className="page" style={{ color: 'var(--muted)' }}>Загрузка…</div>

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav(-1)} style={{ background: 'none', border: 'none', fontSize: 20, color: '#aaa' }}>‹</button>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>✏️ Редактировать урок</span>
        {msg && <span style={{ marginLeft: 'auto', color: msg.startsWith('✅') ? '#4ade80' : '#f87171', fontSize: 13 }}>{msg}</span>}
      </div>

      <div className="page-wide">

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 14 }}>Основное</h3>
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Тема</label>
          <input className="input" value={form.topic} onChange={e => setF('topic', e.target.value)} style={{ marginBottom: 12 }} />
          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Игровой контекст</label>
          <input className="input" value={form.context_theme} onChange={e => setF('context_theme', e.target.value)} style={{ marginBottom: 12 }} />
          <div style={{ display: 'flex', gap: 14 }}>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Монет за урок</label>
              <input className="input" type="number" value={form.coins_lesson} onChange={e => setF('coins_lesson', e.target.value)} style={{ width: 120 }} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Монет за финал</label>
              <input className="input" type="number" value={form.coins_boss} onChange={e => setF('coins_boss', e.target.value)} style={{ width: 120 }} />
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Вступление</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14 }}>
            Если загружена иллюстрация — в уроке она полностью заменяет текст истории (как на примере «Дело №3»). Без картинки показывается текст ниже.
          </p>

          <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', marginBottom: 16 }}>
            <div style={{
              width: 160, height: 200, borderRadius: 10, background: '#f1f3f7', border: '1px solid var(--border)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0,
            }}>
              {lesson.infographic
                ? <img src={lesson.infographic} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : <span style={{ color: 'var(--muted)', fontSize: 12, textAlign: 'center', padding: 8 }}>нет иллюстрации</span>}
            </div>
            <div>
              <input ref={imgInput} type="file" accept="image/*" style={{ display: 'none' }}
                     onChange={e => { if (e.target.files[0]) uploadImage(e.target.files[0]); e.target.value = '' }} />
              <button className="btn btn-sm" disabled={uploading === 'image'} onClick={() => imgInput.current.click()} style={{ marginRight: 8 }}>
                {uploading === 'image' ? 'Загрузка…' : (lesson.infographic ? 'Заменить' : 'Загрузить иллюстрацию')}
              </button>
              {lesson.infographic && (
                <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }} onClick={removeImage}>Убрать</button>
              )}
              <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8, maxWidth: 320 }}>
                Иллюстрацию можно сгенерировать во внешнем сервисе (например, в стиле детективного комикса, как «Дело №3») и просто загрузить сюда файлом.
              </p>
            </div>
          </div>

          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Текст истории (запасной вариант, если без картинки)</label>
          <textarea className="input" rows={6} value={form.explanation_game} onChange={e => setF('explanation_game', e.target.value)} style={{ marginBottom: 12 }} />

          <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Официальное объяснение (не показывается в уроке, хранится для справки)</label>
          <textarea className="input" rows={3} value={form.explanation} onChange={e => setF('explanation', e.target.value)} />
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Аудио-улика (необязательно)</h3>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
            {lesson.audio_file && <audio controls src={lesson.audio_file} style={{ maxWidth: 260 }} />}
            <input ref={audioInput} type="file" accept="audio/*" style={{ display: 'none' }}
                   onChange={e => { if (e.target.files[0]) uploadAudio(e.target.files[0]); e.target.value = '' }} />
            <button className="btn btn-sm" disabled={uploading === 'audio'} onClick={() => audioInput.current.click()}>
              {uploading === 'audio' ? 'Загрузка…' : (lesson.audio_file ? 'Заменить' : 'Загрузить')}
            </button>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Вопросы (JSON)</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>
            Массив объектов: text, options (4 строки), correct (индекс 0-3), hint, explanation.
          </p>
          <textarea className="input" rows={16} style={{ fontFamily: 'monospace', fontSize: 13 }}
                    value={questionsText} onChange={e => setQuestionsText(e.target.value)} />
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontWeight: 700, marginBottom: 6 }}>Финальное задание (JSON, можно оставить пустым)</h3>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 10 }}>Объект: text, solution, hint1, hint2.</p>
          <textarea className="input" rows={8} style={{ fontFamily: 'monospace', fontSize: 13 }}
                    value={bossText} onChange={e => setBossText(e.target.value)} placeholder="{}" />
        </div>

        {jsonErr && <p style={{ color: 'var(--red)', marginBottom: 14 }}>{jsonErr}</p>}

        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end', paddingBottom: 40 }}>
          <button className="btn" onClick={() => window.open(`/lesson/${id}`, '_blank')}>👁 Посмотреть</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Сохраняю…' : '💾 Сохранить'}</button>
        </div>
      </div>
    </div>
  )
}
