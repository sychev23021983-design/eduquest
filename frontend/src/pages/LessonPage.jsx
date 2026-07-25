import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../detective-theme.css'
import '../castle-theme.css'
import '../game-theme.css'

// Тексты интерфейса урока зависят от lesson.context_theme — так один и тот же компонент/CSS
// (cork-board вёрстка detective-theme.css) можно переиспользовать для разных сюжетов предмета,
// не показывая, например, «Дело раскрыто» в уроке про редакцию газеты. Модель данных не меняется
// (по-прежнему lesson_id, questions, boss_task и т.п.) — темизируются только подписи и иконки.
// Неизвестный/отсутствующий context_theme -> 'detective' (старое поведение, ничего не ломает).
const THEMES = {
  detective: {
    icon: '🔍',
    loading: '🔍 Открываю дело…',
    stamp: id => `ДЕЛО №${id}`,
    coverEyebrow: 'История дела',
    audioEyebrow: 'Аудио-улика',
    coinsNoteLabel: 'За расследование',
    startBtn: n => n > 0 ? `Открыть дело — ${n} улик ›` : 'Открыть дело ›',
    subIntro: 'Дело открыто',
    subQuestions: (cur, total) => `Улика ${cur} из ${total}`,
    subBoss: 'Финальное задание',
    subDone: 'Дело раскрыто',
    questionEyebrow: n => `Улика №${n}`,
    wrongExtra: perQ => `, эта улика не принесёт до ${perQ} 🪙 к награде`,
    nextQuestionBtn: 'Следующая улика →',
    toBossBtn: 'Финальное задание →',
    toDoneBtn: 'Закрыть дело →',
    bossEyebrow: '⚔️ Финальное задание',
    bossTitle: 'Разгадай последнюю улику',
    bossReward: n => `Награда: +${n} монет за раскрытие!`,
    bossSubmitBtn: 'Сдать решение →',
    bossCorrect: '✅ Разгадано верно!',
    bossWrong: '❌ Не совсем так, но вот разгадка:',
    bossSolutionLabel: 'Разгадка:',
    bossCloseBtn: 'Понятно, закрыть дело →',
    finaleTitle: 'Дело раскрыто!',
    rank: pct => pct === 100 ? 'Детектив — высшая категория!'
               : pct >= 80  ? 'Детектив I уровня'
               : pct >= 60  ? 'Детектив-стажёр'
               : pct >= 40  ? 'Дело почти раскрыто — есть над чем поработать'
               :              'В следующий раз след будет вернее',
    scoreLabel: 'Разгаданных улик',
    coinsForQuestions: (score, total) => `За улики (${score}/${total})`,
    coinsForBoss: 'За финальное задание ⚔️',
    mistakeNote: n => `${n} ${n === 1 ? 'улика уменьшила' : 'улики уменьшили'} награду за расследование — в следующий раз выбирай ответ вдумчивее!`,
    retryNote: '💡 Пройди дело ещё раз, чтобы собрать больше улик и монет!',
  },
  newsroom: {
    icon: '📰',
    loading: '📰 Открываю папку архива…',
    stamp: id => `ВЫПУСК №${id}`,
    coverEyebrow: 'Из архива редакции',
    audioEyebrow: 'Аудиозапись',
    coinsNoteLabel: 'За материал',
    startBtn: n => n > 0 ? `Открыть папку — ${n} материалов ›` : 'Открыть папку ›',
    subIntro: 'Папка открыта',
    subQuestions: (cur, total) => `Материал ${cur} из ${total}`,
    subBoss: 'Финальная полоса',
    subDone: 'Номер подписан в печать',
    questionEyebrow: n => `Материал №${n}`,
    wrongExtra: perQ => `, эта правка не принесёт до ${perQ} 🪙 к награде`,
    nextQuestionBtn: 'Следующий материал →',
    toBossBtn: 'Финальная полоса →',
    toDoneBtn: 'Сдать номер →',
    bossEyebrow: '🖋️ Финальная полоса',
    bossTitle: 'Подготовь последнюю полосу',
    bossReward: n => `Награда: +${n} монет за сдачу номера!`,
    bossSubmitBtn: 'Сдать в печать →',
    bossCorrect: '✅ Готово к печати!',
    bossWrong: '❌ Не совсем так — вот как правильно:',
    bossSolutionLabel: 'Правильный вариант:',
    bossCloseBtn: 'Понятно, сдать номер →',
    finaleTitle: 'Номер подписан в печать!',
    rank: pct => pct === 100 ? 'Главный редактор — высшая категория!'
               : pct >= 80  ? 'Редактор I категории'
               : pct >= 60  ? 'Редактор-стажёр'
               : pct >= 40  ? 'Номер почти готов — есть над чем поработать'
               :              'В следующий раз вычитка будет вернее',
    scoreLabel: 'Выверенных материалов',
    coinsForQuestions: (score, total) => `За материалы (${score}/${total})`,
    coinsForBoss: 'За финальную полосу 🖋️',
    mistakeNote: n => `${n} ${n === 1 ? 'материал потребовал' : 'материала потребовали'} правку — в следующий раз выбирай ответ вдумчивее!`,
    retryNote: '💡 Пройди номер ещё раз, чтобы собрать больше монет!',
  },
  castle: {
    icon: '🏰',
    loading: '🏰 Открываю карту испытания…',
    stamp: id => `ИСПЫТАНИЕ №${id}`,
    coverEyebrow: 'Легенда испытания',
    audioEyebrow: 'Голос Профессора',
    coinsNoteLabel: 'За испытание',
    startBtn: n => n > 0 ? `Войти в испытание — ${n} задач ›` : 'Войти в испытание ›',
    subIntro: 'Испытание начато',
    subQuestions: (cur, total) => `Задача ${cur} из ${total}`,
    subBoss: 'Финальное состязание',
    subDone: 'Путь открыт',
    questionEyebrow: n => `Задача №${n}`,
    wrongExtra: perQ => `, эта задача не принесёт до ${perQ} 🪙 к награде`,
    nextQuestionBtn: 'Следующая задача →',
    toBossBtn: 'Финальное состязание →',
    toDoneBtn: 'Открыть путь →',
    bossEyebrow: '⚔️ Финальное состязание',
    bossTitle: 'Пройди последнее испытание Хранителя',
    bossReward: n => `Награда: +${n} монет за победу!`,
    bossSubmitBtn: 'Дать ответ →',
    bossCorrect: '✅ Верно! Путь открыт!',
    bossWrong: '❌ Не совсем так, но вот решение:',
    bossSolutionLabel: 'Решение:',
    bossCloseBtn: 'Понятно, открыть путь →',
    finaleTitle: 'Испытание пройдено!',
    rank: pct => pct === 100 ? 'Великий Исследователь — высшая категория!'
               : pct >= 80  ? 'Исследователь I уровня'
               : pct >= 60  ? 'Исследователь-новичок'
               : pct >= 40  ? 'Путь почти открыт — есть над чем подумать'
               :              'В следующий раз рассуждай внимательнее',
    scoreLabel: 'Решённых задач',
    coinsForQuestions: (score, total) => `За задачи (${score}/${total})`,
    coinsForBoss: 'За финальное состязание ⚔️',
    mistakeNote: n => `${n} ${n === 1 ? 'задача уменьшила' : 'задачи уменьшили'} награду за испытание — в следующий раз рассуждай внимательнее!`,
    retryNote: '💡 Пройди испытание ещё раз, чтобы решить больше задач и собрать больше монет!',
  },
}
function themeFor(lesson) {
  return THEMES[lesson?.context_theme] || THEMES.detective
}

export default function LessonPage() {
  const { id } = useParams()
  const { token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const correctAudioRef = useRef(null)
  const wrongAudioRef   = useRef(null)

  function playCorrectSound() {
    if (settings?.sound_correct && correctAudioRef.current) {
      correctAudioRef.current.currentTime = 0
      correctAudioRef.current.play().catch(e => console.warn('Не удалось проиграть звук правильного ответа:', e))
    }
  }
  function playWrongSound() {
    if (settings?.sound_wrong && wrongAudioRef.current) {
      wrongAudioRef.current.currentTime = 0
      wrongAudioRef.current.play().catch(e => console.warn('Не удалось проиграть звук неправильного ответа:', e))
    }
  }

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
  const [bossCorrect, setBossCorrect] = useState(null)
  const [lessonCoinsEarned, setLessonCoinsEarned] = useState(0)
  const [bossCoinsEarned,   setBossCoinsEarned]   = useState(0)
  const [mistakeCount, setMistakeCount] = useState(0)
  const [bossSubmitting, setBossSubmitting] = useState(false)
  const [slideIndex, setSlideIndex] = useState(0)

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
    const q = questions[current]
    if (idx === q.correct) {
      setScore(s => s + 1)
      playCorrectSound()
    } else {
      setMistakeCount(c => c + 1)
      playWrongSound()
      api.logMistake(token, {
        lesson_id: Number(id),
        question_text: q.text,
        chosen_text: q.options?.[idx] ?? null,
        correct_text: q.options?.[q.correct] ?? null,
      }).catch(() => {})
    }
  }

  function nextQuestion() {
    const next = current + 1
    if (next < questions.length) {
      setCurrent(next); setSelected(null); setAnswered(false)
    } else {
      setPhase(lesson.boss_task ? 'boss' : 'done')
      if (!lesson.boss_task) finishLessonSimple()
    }
  }

  async function checkBoss() {
    if (!bossInput.trim() || bossSubmitting) return
    setBossSubmitting(true)
    try {
      const res = await api.finishLesson(token, {
        progress_id: progressId, score, total: questions.length, boss_done: true, boss_answer: bossInput,
      })
      setCoins(res.coins_earned)
      setLessonCoinsEarned(res.lesson_coins)
      setBossCoinsEarned(res.boss_coins)
      setBossCorrect(res.boss_correct)
      setBossWasDone(true)
      setBossCheck('submitted')
      if (res.boss_correct) playCorrectSound(); else playWrongSound()
    } finally {
      setBossSubmitting(false)
    }
  }

  function closeCase() {
    setPhase('done')
  }

  async function finishLessonSimple() {
    const res = await api.finishLesson(token, { progress_id: progressId, score, total: questions.length, boss_done: false })
    setCoins(res.coins_earned)
    setLessonCoinsEarned(res.lesson_coins)
    setPhase('done')
  }

  if (!lesson) return (
    <div className="detective-lesson">
      <div className="dl-wrap" style={{ paddingTop: 60, textAlign: 'center', color: 'var(--paper)' }}>🔍 Открываю…</div>
    </div>
  )

  // Урок-слайдшоу (lesson_type='slideshow'): никаких вопросов, объяснений, монет — только
  // упорядоченная колода картинок и кнопки «вперёд»/«назад». Картинки берутся из настроек сайта
  // по названиям слотов, перечисленным в lesson.slides (см. Settings.jsx, раздел
  // «Архитектура математики — слайды»); если слот ещё не заполнен — показывается плейсхолдер.
  if (lesson.lesson_type === 'slideshow') {
    const slides = (() => { try { return JSON.parse(lesson.slides || '[]') } catch { return [] } })()
    const total = slides.length
    const clamped = Math.min(Math.max(slideIndex, 0), Math.max(total - 1, 0))
    const slot = slides[clamped]
    const url = slot ? settings?.[slot] : null
    return (
      <div className="game-home">
        <div className="gh-map-topbar">
          <button className="gh-back-btn" onClick={() => nav(lesson.subject ? `/subject/${lesson.subject}` : '/')}>‹</button>
          <div className="gh-map-title">
            <span className="gh-map-title-text">📐 {lesson.topic}</span>
          </div>
        </div>

        {total === 0 && (
          <div className="gh-wrap gh-empty" style={{ paddingTop: 60 }}>Слайды ещё не добавлены 🖼️</div>
        )}

        {total > 0 && (
          <div className="gh-slideshow-wrap">
            <button className="gh-slideshow-arrow prev" onClick={() => setSlideIndex(i => Math.max(0, i - 1))} disabled={clamped === 0} aria-label="Предыдущий">‹</button>
            <div className="gh-slideshow-img-box">
              {url ? (
                <img src={url} alt="" />
              ) : (
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: '100%', height: '100%', color: 'var(--gh-muted)',
                  fontSize: '0.9rem', textAlign: 'center', padding: 20,
                }}>
                  Слайд {clamped + 1} ещё не загружен 🖼️
                </div>
              )}
            </div>
            <button className="gh-slideshow-arrow next" onClick={() => setSlideIndex(i => Math.min(total - 1, i + 1))} disabled={clamped === total - 1} aria-label="Следующий">›</button>
            <div className="gh-slideshow-counter" style={{ justifyContent: 'center' }}>{clamped + 1} / {total}</div>
          </div>
        )}
      </div>
    )
  }

  const q = questions[current]
  const boss = (() => { try { return JSON.parse(lesson.boss_task || 'null') } catch { return null } })()
  const stars = score
  const theme = themeFor(lesson)
  const rootThemeClass = lesson?.context_theme === 'castle' ? 'castle-lesson' : 'detective-lesson'

  return (
    <div className={rootThemeClass}>
      <audio ref={correctAudioRef} src={settings?.sound_correct || undefined} preload="auto" style={{ display: 'none' }} />
      <audio ref={wrongAudioRef} src={settings?.sound_wrong || undefined} preload="auto" style={{ display: 'none' }} />
      {/* Top bar */}
      <div className="dl-topbar">
        <button className="dl-back" onClick={() => nav(lesson.subject ? `/subject/${lesson.subject}` : '/')}>‹</button>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <div className="dl-title">🗂 {lesson.topic}</div>
          <div className="dl-sub">
            {phase === 'questions' ? theme.subQuestions(current + 1, questions.length) :
             phase === 'boss' ? theme.subBoss :
             phase === 'done' ? theme.subDone : theme.subIntro}
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
            {!lesson.infographic && (
              <div className="dl-cover">
                <div className="dl-stamp">{theme.stamp(lesson.id)}</div>
                <span className="dl-magnifier">{theme.icon}</span>
                <h1>{lesson.topic}</h1>
              </div>
            )}

            {lesson.infographic ? (
              <img src={lesson.infographic} alt={theme.coverEyebrow} style={{ width: '100%', borderRadius: 14, marginBottom: 16, boxShadow: '0 10px 20px rgba(0,0,0,0.35)' }} />
            ) : (
              <div className="dl-card rot-l">
                <div className="dl-pin" />
                <div className="dl-eyebrow">{theme.coverEyebrow}</div>
                <p>{lesson.explanation_game || lesson.explanation || 'Объяснение скоро появится'}</p>
              </div>
            )}

            {lesson.audio_file && (
              <div className="dl-card rot-l" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div className="dl-pin" />
                <span style={{ fontSize: 22 }}>🎧</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>{theme.audioEyebrow}</div>
                  <audio controls src={lesson.audio_file} style={{ width: '100%' }} />
                </div>
              </div>
            )}

            <div className="dl-coins-note">
              🪙 {theme.coinsNoteLabel}: <b>+{lesson.coins_lesson} монет</b> · за финальное задание: <b>+{lesson.coins_boss} монет</b>
            </div>

            <button className="dl-btn wide" onClick={startLesson}>
              {theme.startBtn(questions.length)}
            </button>
          </div>
        )}

        {/* QUESTIONS */}
        {phase === 'questions' && q && (
          <div>
            <div className="dl-card rot-l">
              <div className="dl-pin" />
              <div className="dl-eyebrow">{theme.questionEyebrow(current + 1)}</div>
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
                    ❌ Мимо{questions.length > 0 && lesson.coins_lesson ? theme.wrongExtra(Math.round(lesson.coins_lesson / questions.length)) : ''}.{' '}
                    {q.explanation || (q.hint ? `Подсказка: ${q.hint}` : '')}
                  </div>
                )}
                <button className="dl-btn wide" onClick={nextQuestion}>
                  {current + 1 < questions.length ? theme.nextQuestionBtn : lesson.boss_task ? theme.toBossBtn : theme.toDoneBtn}
                </button>
              </div>
            )}
          </div>
        )}

        {/* BOSS */}
        {phase === 'boss' && boss && (
          <div>
            <div className="dl-boss-header">
              <div className="dl-eyebrow">{theme.bossEyebrow}</div>
              <h2>{theme.bossTitle}</h2>
              <p>{boss.text}</p>
              <div className="dl-reward">{theme.bossReward(lesson.coins_boss)}</div>
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
                        onClick={checkBoss} disabled={!bossInput.trim() || bossSubmitting}>
                  {bossSubmitting ? 'Проверяю…' : theme.bossSubmitBtn}
                </button>
              </>
            ) : (
              <div className="dl-card rot-l">
                <div className="dl-pin" />
                <div className="dl-eyebrow" style={{ color: bossCorrect ? 'var(--dl-green)' : 'var(--dl-red)' }}>
                  {bossCorrect ? theme.bossCorrect : theme.bossWrong}
                </div>
                {boss.solution && <p><b>{theme.bossSolutionLabel}</b><br />{boss.solution}</p>}
              </div>
            )}
            {bossCheck === 'submitted' && (
              <button className="dl-btn wide" onClick={closeCase}>
                {theme.bossCloseBtn}
              </button>
            )}
          </div>
        )}

        {/* DONE */}
        {phase === 'done' && (() => {
          const total = questions.length || 1
          const pct   = Math.round((score / total) * 100)
          const emoji = pct === 100 ? '🏆' : pct >= 80 ? '🥇' : pct >= 60 ? '🥈' : pct >= 40 ? '🥉' : '📚'
          const rank  = theme.rank(pct)
          const lessonCoins = lessonCoinsEarned
          return (
            <div className="dl-finale">
              <div className="dl-badge">{emoji}</div>
              <h2 style={{ fontFamily: 'var(--font-display)', color: 'var(--paper)', fontSize: '1.3rem', marginBottom: 6 }}>
                {theme.finaleTitle}
              </h2>
              <p style={{ color: '#cfcfe6', marginBottom: 20 }}>{rank}</p>

              <div className="dl-card rot-l" style={{ textAlign: 'left' }}>
                <div className="dl-pin" />
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontWeight: 600 }}>{theme.scoreLabel}</span>
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
                  <span style={{ color: '#8a7a5e' }}>{theme.coinsForQuestions(score, questions.length)}</span>
                  <span style={{ fontWeight: 600 }}>+{lessonCoins}</span>
                </div>
                {bossWasDone && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--paper-dark)', fontSize: 14 }}>
                    <span style={{ color: '#8a7a5e' }}>{theme.coinsForBoss}</span>
                    {bossCorrect ? (
                      <span style={{ fontWeight: 600, color: 'var(--dl-green)' }}>+{bossCoinsEarned}</span>
                    ) : (
                      <span style={{ fontWeight: 600, color: 'var(--dl-red)' }}>✗ не засчитано</span>
                    )}
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0 0', fontSize: 18, fontWeight: 700 }}>
                  <span>Итого</span>
                  <span style={{ color: 'var(--dl-gold)' }}>+{coinsEarned} 🪙</span>
                </div>
              </div>

              {mistakeCount > 0 && (
                <div className="dl-coins-note" style={{ textAlign: 'left' }}>
                  🤔 {theme.mistakeNote(mistakeCount)}
                </div>
              )}

              {pct < 80 && questions.length > 0 && (
                <div className="dl-coins-note" style={{ textAlign: 'left' }}>
                  {theme.retryNote}
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
