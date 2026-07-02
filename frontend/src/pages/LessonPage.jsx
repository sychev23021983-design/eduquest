import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'
import '../detective-theme.css'

const WRONG_ANSWER_PENALTY = 5

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
  const [bossWasDone, setBossWasDone] = useState(false)
  const [coinsLost,   setCoinsLost] = useState(0)
  const [bossSubmitting, setBossSubmitting] = useState(false)

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
    if (idx === questions[current].correct) {
      setScore(s => s + 1)
    } else {
      setCoinsLost(c => c + WRONG_ANSWER_PENALTY)
      api.coinPenalty(token, {
        lesson_id: Number(id), amount: WRONG_ANSWER_PENALTY,
        note: `Неверный ответ: ${lesson.topic}`,
      }).catch(() => {})
    }
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
    setBossWasDone(true)
  }

  async function finishAfterBoss() {
    setBossSubmitting(true)
    await finishLesson(true)
    setBossSubmitting(false)
  }

  async function finishLesson(boss) {
    const res = await api.finishLesson(token, { progress_id: progressId, score, boss_done: boss })
    setCoins(res.coins_earned)
    setPhase('done')
  }

  if (!lesson) return (
    <div className="detective-lesson">
      <div className="dl-wrap" style={{ paddingTop: 60, textAlign: 'center', color: 'var(--paper)' }}>🔍 Открываю дело…</div>
    </div>
  )

  const q = questions[current]
  const boss = (() => { try { return JSON.parse(lesson.boss_task || 'null') } catch { return null } })()
  const stars = score

  return (
    <div className="detective-lesson">
      {/* Top bar */}
      <div className="dl-topbar">
        <button className="dl-back" onClick={() => nav('/')}>‹</button>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <div className="dl-title">🗂 {lesson.topic}</div>
          <div className="dl-sub">
            {phase === 'questions' ? `Улика ${current + 1} из ${questions.length}` :
             phase === 'boss' ? 'Финальное задание' :
             phase === 'done' ? 'Дело раскрыто' : 'Дело открыто'}
          </div>
        </div>
        {phase === 'questions' && (
          <div className="dl-dots">
            {questions.map((_, i) => (
              <div key={i} className={`dl-dot ${i < current ? 'done' : i === current ? 'current' : ''}`} />
            ))}
          </div>
        )}
        {(phase === 'questions' || phase === 'done') && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: 'var(--dl-gold)' }}>⭐ {stars}</span>
        )}
      </div>

      <div className="dl-wrap">

        {/* INTRO / COVER */}
        {phase === 'intro' && (
          <div>
            <div className="dl-cover">
              <div className="dl-stamp">ДЕЛО №{lesson.id}</div>
              <span className="dl-magnifier">🔍</span>
              <h1>{lesson.topic}</h1>
            </div>

            {lesson.infographic ? (
              <img src={lesson.infographic} alt="История дела" style={{ width: '100%', borderRadius: 14, marginBottom: 16, boxShadow: '0 10px 20px rgba(0,0,0,0.35)' }} />
            ) : (
              <div className="dl-card rot-l">
                <div className="dl-pin" />
                <div className="dl-eyebrow">История дела</div>
                <p>{lesson.explanation_game || lesson.explanation || 'Объяснение скоро появится'}</p>
              </div>
            )}

            {lesson.audio_file && (
              <div className="dl-card rot-l" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="dl-pin" />
                <span style={{ fontSize: 22 }}>🎧</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>Аудио-улика</div>
                  <audio controls src={lesson.audio_file} style={{ width: '100%' }} />
                </div>
              </div>
            )}

            <div className="dl-coins-note">
              🪙 За расследование: <b>+{lesson.coins_lesson} монет</b> · за финальное задание: <b>+{lesson.coins_boss} монет</b>
            </div>

            <button className="dl-btn wide" onClick={startLesson}>
              {questions.length > 0 ? `Открыть дело — ${questions.length} улик ›` : 'Открыть дело ›'}
            </button>
          </div>
        )}

        {/* QUESTIONS */}
        {phase === 'questions' && q && (
          <div>
            <div className="dl-card rot-l">
              <div className="dl-pin" />
              <div className="dl-eyebrow">Улика №{current + 1}</div>
              <h2 style={{ fontSize: '1.1rem' }}>{q.text}</h2>
            </div>

            <div className="dl-options">
              {q.options.map((opt, i) => {
                let cls = 'dl-option'
                if (answered) {
                  if (i === q.correct) cls += ' correct'
                  else if (i === selected) cls += ' wrong'
                }
                return (
                  <button key={i} className={cls} disabled={answered} onClick={() => selectAnswer(i)}>
                    <span className="dl-letter">{['А', 'Б', 'В', 'Г'][i]})</span>{opt}
                  </button>
                )
              })}
            </div>

            {answered && (
              <div>
                {selected === q.correct ? (
                  <div className="dl-feedback correct">✅ Точно! {q.explanation || ''}</div>
                ) : (
                  <div className="dl-feedback wrong">
                    ❌ Мимо, −{WRONG_ANSWER_PENALTY} 🪙. {q.explanation || (q.hint ? `Подсказка: ${q.hint}` : '')}
                  </div>
                )}
                <button className="dl-btn wide" onClick={nextQuestion}>
                  {current + 1 < questions.length ? 'Следующая улика →' : lesson.boss_task ? 'Финальное задание →' : 'Закрыть дело →'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* BOSS */}
        {phase === 'boss' && boss && (
          <div>
            <div className="dl-boss-header">
              <div className="dl-eyebrow">⚔️ Финальное задание</div>
              <h2>Разгадай последнюю улику</h2>
              <p>{boss.text}</p>
              <div className="dl-reward">Награда: +{lesson.coins_boss} монет за раскрытие!</div>
            </div>

            {bossCheck !== 'submitted' ? (
              <>
                <textarea className="dl-textarea" placeholder="Запиши своё решение здесь..."
                          value={bossInput} onChange={e => setBossInput(e.target.value)} />
                {boss.hint1 && (
                  <details className="dl-hint">
                    <summary>💡 Подсказка 1</summary>
                    <p>{boss.hint1}</p>
                  </details>
                )}
                {boss.hint2 && (
                  <details className="dl-hint">
                    <summary>💡 Подсказка 2</summary>
                    <p>{boss.hint2}</p>
                  </details>
                )}
                <button className="dl-btn secondary wide" style={{ marginTop: 14 }}
                        onClick={checkBoss} disabled={!bossInput.trim()}>
                  Сдать решение →
                </button>
              </>
            ) : (
              <div className="dl-card rot-l">
                <div className="dl-pin" />
                <div className="dl-eyebrow" style={{ color: 'var(--dl-green)' }}>✅ Решение принято</div>
                {boss.solution && <p><b>Разгадка:</b><br />{boss.solution}</p>}
              </div>
            )}
            {bossCheck === 'submitted' && (
              <button className="dl-btn wide" onClick={finishAfterBoss} disabled={bossSubmitting}>
                {bossSubmitting ? 'Закрываю дело…' : 'Понятно, закрыть дело →'}
              </button>
            )}
          </div>
        )}

        {/* DONE */}
        {phase === 'done' && (() => {
          const total = questions.length || 1
          const pct   = Math.round((score / total) * 100)
          const emoji = pct === 100 ? '🏆' : pct >= 80 ? '🥇' : pct >= 60 ? '🥈' : pct >= 40 ? '🥉' : '📚'
          const rank  = pct === 100 ? 'Детектив чисел — высшая категория!'
                      : pct >= 80   ? 'Детектив чисел I уровня'
                      : pct >= 60   ? 'Детектив-стажёр'
                      : pct >= 40   ? 'Дело почти раскрыто — есть над чем поработать'
                      :               'В следующий раз след будет вернее'
          const lessonCoins = coinsEarned - (bossWasDone && lesson ? lesson.coins_boss : 0)
          return (
            <div className="dl-finale">
              <div className="dl-badge">{emoji}</div>
              <h2 style={{ fontFamily: 'var(--font-display)', color: 'var(--paper)', fontSize: '1.3rem', marginBottom: 6 }}>
                Дело раскрыто!
              </h2>
              <p style={{ color: '#cfcfe6', marginBottom: 20 }}>{rank}</p>

              <div className="dl-card rot-l" style={{ textAlign: 'left' }}>
                <div className="dl-pin" />
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>Разгаданных улик</span>
                  <span style={{ fontWeight: 700, color: pct >= 60 ? 'var(--dl-green)' : 'var(--dl-red)' }}>
                    {score} / {questions.length}
                  </span>
                </div>
                <div className="dl-scorebar-track">
                  <div className="dl-scorebar-fill" style={{
                    width: `${pct}%`,
                    background: pct === 100 ? 'var(--dl-green)' : pct >= 60 ? 'var(--dl-navy)' : 'var(--dl-gold)'
                  }} />
                </div>
                <div style={{ textAlign: 'right', fontSize: 13, color: '#8a7a5e', marginTop: 4 }}>{pct}%</div>
              </div>

              <div className="dl-card rot-r" style={{ textAlign: 'left' }}>
                <div className="dl-pin" />
                <div style={{ fontWeight: 600, marginBottom: 12 }}>🪙 Заработано монет</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--paper-dark)', fontSize: 14 }}>
                  <span style={{ color: '#8a7a5e' }}>За улики ({score}/{questions.length})</span>
                  <span style={{ fontWeight: 600 }}>+{lessonCoins}</span>
                </div>
                {bossWasDone && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--paper-dark)', fontSize: 14 }}>
                    <span style={{ color: '#8a7a5e' }}>За финальное задание ⚔️</span>
                    <span style={{ fontWeight: 600, color: 'var(--dl-green)' }}>+{lesson?.coins_boss || 30}</span>
                  </div>
                )}
                {coinsLost > 0 && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--paper-dark)', fontSize: 14 }}>
                    <span style={{ color: '#8a7a5e' }}>Штраф за неверные ответы</span>
                    <span style={{ fontWeight: 600, color: 'var(--dl-red)' }}>−{coinsLost}</span>
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0 0', fontSize: 18, fontWeight: 700 }}>
                  <span>Итого</span>
                  <span style={{ color: 'var(--dl-gold)' }}>+{coinsEarned - coinsLost} 🪙</span>
                </div>
              </div>

              {coinsLost > 0 && (
                <div className="dl-coins-note" style={{ textAlign: 'left' }}>
                  🤔 В следующий раз выбирай ответ вдумчивее — за ошибки списываются монеты!
                </div>
              )}

              {pct < 80 && questions.length > 0 && (
                <div className="dl-coins-note" style={{ textAlign: 'left' }}>
                  💡 Пройди дело ещё раз, чтобы собрать больше улик и монет!
                </div>
              )}

              <button className="dl-btn wide" onClick={() => nav('/')}>На главную →</button>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
