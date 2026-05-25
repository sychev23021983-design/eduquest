import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

export default function LessonPage() {
  const { id } = useParams()
  const { token } = useAuth()
  const nav = useNavigate()

  const [lesson,     setLesson]     = useState(null)
  const [progressId, setProgressId] = useState(null)
  const [phase,      setPhase]      = useState('intro')   // intro | questions | boss | done
  const [questions,  setQuestions]  = useState([])
  const [current,    setCurrent]    = useState(0)
  const [selected,   setSelected]   = useState(null)
  const [answered,   setAnswered]   = useState(false)
  const [score,      setScore]      = useState(0)
  const [bossInput,  setBossInput]  = useState('')
  const [bossCheck,  setBossCheck]  = useState(null)
  const [coinsEarned, setCoins]     = useState(0)
  const [audio,      setAudio]      = useState(null)

  useEffect(() => { loadLesson() }, [id])

  async function loadLesson() {
    const l = await api.lesson(token, id)
    setLesson(l)
    try { setQuestions(JSON.parse(l.questions || '[]')) } catch { setQuestions([]) }
  }

  async function startLesson() {
    const res = await api.startLesson(token, Number(id))
    setProgressId(res.progress_id)
    setPhase(questions.length > 0 ? 'questions' : (lesson.boss_task ? 'boss' : 'done'))
  }

  function selectAnswer(idx) {
    if (answered) return
    setSelected(idx)
    setAnswered(true)
    if (idx === questions[current].correct) setScore(s => s + 1)
  }

  function nextQuestion() {
    const next = current + 1
    if (next < questions.length) {
      setCurrent(next); setSelected(null); setAnswered(false)
    } else {
      setPhase(lesson.boss_task ? 'boss' : 'done')
      if (!lesson.boss_task) finishLesson(false)
    }
  }

  function checkBoss() {
    if (!bossInput.trim()) return
    setBossCheck('submitted')
    finishLesson(true)
  }

  async function finishLesson(boss) {
    const res = await api.finishLesson(token, { progress_id: progressId, score, boss_done: boss })
    setCoins(res.coins_earned)
    setPhase('done')
  }

  if (!lesson) return <div className="page" style={{ color: 'var(--muted)', paddingTop: 60, textAlign: 'center' }}>Загрузка...</div>

  const q = questions[current]
  const boss = (() => { try { return JSON.parse(lesson.boss_task || 'null') } catch { return null } })()

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      {/* Header */}
      <div style={{ background: '#fff', borderBottom: '1px solid var(--border)', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <button onClick={() => nav('/')} style={{ background: 'none', border: 'none', fontSize: 20, color: 'var(--muted)' }}>‹</button>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600 }}>{lesson.topic}</div>
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            {phase === 'questions' ? `Вопрос ${current + 1} из ${questions.length}` :
             phase === 'boss' ? 'Финальная задача' :
             phase === 'done' ? 'Урок завершён!' : 'Введение'}
          </div>
        </div>
        {phase === 'questions' && (
          <div style={{ display: 'flex', gap: 4 }}>
            {questions.map((_, i) => (
              <div key={i} style={{ width: 8, height: 8, borderRadius: '50%',
                background: i < current ? 'var(--green)' : i === current ? 'var(--blue)' : 'var(--border)' }} />
            ))}
          </div>
        )}
      </div>

      <div className="page" style={{ maxWidth: 680 }}>

        {/* INTRO */}
        {phase === 'intro' && (
          <div>
            {lesson.infographic && (
              <img src={lesson.infographic} alt="инфографика" style={{ width: '100%', borderRadius: 12, marginBottom: 16 }} />
            )}
            {lesson.audio_file && (
              <div className="card" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 24 }}>🎧</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, marginBottom: 6 }}>Аудио-объяснение</div>
                  <audio controls src={lesson.audio_file} style={{ width: '100%' }} />
                </div>
              </div>
            )}
            <div className="card" style={{ marginBottom: 16, borderLeft: '4px solid var(--blue)' }}>
              <div style={{ fontWeight: 600, marginBottom: 8, color: 'var(--blue)' }}>
                {lesson.context_theme === 'minecraft' ? '⛏️ История Стива' : '🎮 Игровая история'}
              </div>
              <p style={{ lineHeight: 1.7 }}>{lesson.explanation_game || lesson.explanation || 'Объяснение скоро появится'}</p>
            </div>
            {lesson.explanation_game && lesson.explanation && (
              <div className="card" style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📖 Официальное объяснение</div>
                <p style={{ lineHeight: 1.7, color: 'var(--muted)' }}>{lesson.explanation}</p>
              </div>
            )}
            <div style={{ background: 'var(--amber-light)', borderRadius: 12, padding: 14, marginBottom: 20, display: 'flex', gap: 10 }}>
              <span>🪙</span>
              <span style={{ fontSize: 14, color: 'var(--amber)' }}>
                За урок: <b>+{lesson.coins_lesson} монет</b> · За финальную задачу: <b>+{lesson.coins_boss} монет</b>
              </span>
            </div>
            <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '13px 0', fontSize: 16 }}
                    onClick={startLesson}>
              {questions.length > 0 ? `Начать — ${questions.length} вопросов ›` : 'Начать урок ›'}
            </button>
          </div>
        )}

        {/* QUESTIONS */}
        {phase === 'questions' && q && (
          <div>
            <div className="card" style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 8 }}>Вопрос {current + 1} из {questions.length}</div>
              <p style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.5 }}>{q.text}</p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
              {q.options.map((opt, i) => {
                let bg = '#fff', border = 'var(--border)', color = 'var(--text)'
                if (answered) {
                  if (i === q.correct)          { bg = 'var(--green-light)'; border = 'var(--green)'; color = 'var(--green)' }
                  else if (i === selected)       { bg = 'var(--red-light)';   border = 'var(--red)';   color = 'var(--red)' }
                }
                return (
                  <button key={i} onClick={() => selectAnswer(i)} style={{
                    padding: '12px 16px', border: `1.5px solid ${border}`, borderRadius: 10,
                    background: bg, color, textAlign: 'left', fontSize: 15, fontWeight: answered && i === q.correct ? 600 : 400,
                    cursor: answered ? 'default' : 'pointer'
                  }}>
                    <span style={{ fontWeight: 600, marginRight: 8 }}>{['А', 'Б', 'В', 'Г'][i]})</span>{opt}
                  </button>
                )
              })}
            </div>
            {answered && (
              <div>
                {selected === q.correct ? (
                  <div style={{ background: 'var(--green-light)', borderRadius: 10, padding: '12px 16px', marginBottom: 14, color: 'var(--green)', fontWeight: 500 }}>
                    ✅ Верно! {q.explanation || ''}
                  </div>
                ) : (
                  <div style={{ background: 'var(--red-light)', borderRadius: 10, padding: '12px 16px', marginBottom: 14 }}>
                    <div style={{ color: 'var(--red)', fontWeight: 500, marginBottom: 4 }}>❌ Неверно</div>
                    <div style={{ fontSize: 14 }}>{q.explanation || (q.hint ? `Подсказка: ${q.hint}` : '')}</div>
                  </div>
                )}
                <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} onClick={nextQuestion}>
                  {current + 1 < questions.length ? 'Следующий вопрос →' : lesson.boss_task ? 'Финальная задача →' : 'Завершить урок →'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* BOSS */}
        {phase === 'boss' && boss && (
          <div>
            <div style={{ background: '#1a1a2e', borderRadius: 14, padding: '20px', marginBottom: 20, color: '#fff' }}>
              <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 8 }}>⚔️ Финальная задача — Босс!</div>
              <p style={{ lineHeight: 1.7, color: '#c8c8e8' }}>{boss.text}</p>
              <div style={{ marginTop: 12, fontSize: 13, color: '#fbbf24' }}>Награда: +{lesson.coins_boss} монет за решение!</div>
            </div>
            {bossCheck !== 'submitted' ? (
              <>
                <textarea className="input" rows={4} placeholder="Запиши своё решение здесь..."
                          value={bossInput} onChange={e => setBossInput(e.target.value)}
                          style={{ marginBottom: 12 }} />
                {boss.hint1 && (
                  <details style={{ marginBottom: 10 }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 14 }}>💡 Подсказка 1</summary>
                    <p style={{ marginTop: 6, fontSize: 14, padding: '8px 12px', background: 'var(--amber-light)', borderRadius: 8 }}>{boss.hint1}</p>
                  </details>
                )}
                {boss.hint2 && (
                  <details style={{ marginBottom: 14 }}>
                    <summary style={{ cursor: 'pointer', color: 'var(--muted)', fontSize: 14 }}>💡 Подсказка 2</summary>
                    <p style={{ marginTop: 6, fontSize: 14, padding: '8px 12px', background: 'var(--amber-light)', borderRadius: 8 }}>{boss.hint2}</p>
                  </details>
                )}
                <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '13px 0' }}
                        onClick={checkBoss} disabled={!bossInput.trim()}>
                  Сдать решение →
                </button>
              </>
            ) : (
              <div style={{ background: 'var(--green-light)', borderRadius: 12, padding: 16, marginBottom: 14 }}>
                <div style={{ fontWeight: 600, color: 'var(--green)', marginBottom: 8 }}>✅ Решение принято!</div>
                {boss.solution && <div style={{ fontSize: 14, lineHeight: 1.6 }}><b>Правильное решение:</b><br />{boss.solution}</div>}
              </div>
            )}
          </div>
        )}

        {/* DONE */}
        {phase === 'done' && (
          <div style={{ textAlign: 'center', paddingTop: 40 }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>🏆</div>
            <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>Урок завершён!</h2>
            <div style={{ fontSize: 16, color: 'var(--muted)', marginBottom: 24 }}>
              Правильных ответов: {score} из {questions.length}
            </div>
            <div style={{ background: 'var(--amber-light)', borderRadius: 14, padding: '20px', display: 'inline-block', marginBottom: 32 }}>
              <div style={{ fontSize: 36, fontWeight: 800, color: 'var(--amber)' }}>+{coinsEarned} 🪙</div>
              <div style={{ fontSize: 14, color: 'var(--amber)' }}>монет заработано!</div>
            </div>
            <br />
            <button className="btn btn-primary" style={{ padding: '13px 40px', fontSize: 16 }} onClick={() => nav('/')}>
              На главную →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
