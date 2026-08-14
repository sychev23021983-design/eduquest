import { useState } from 'react'

// Показ одного задания «Навыков»: картинка + до 3 подсказок, открываемых по одной,
// и кнопка «Сдаюсь» (доступна после того, как открыты все подсказки), которая
// показывает правильный ответ. key={skill.id} на месте использования сбрасывает
// состояние при смене задания.
export function SkillTaskView({ skill }) {
  const [shown, setShown] = useState(0)
  const [gaveUp, setGaveUp] = useState(false)
  const hints = [skill.hint1, skill.hint2, skill.hint3].filter(h => h && h.trim())
  const allHintsShown = shown >= hints.length
  const hasAnswer = !!(skill.answer && skill.answer.trim())

  return (
    <div className="gh-skill-task">
      {skill.content && (
        <div className="gh-skill-hint-box" style={{ marginBottom: 14, whiteSpace: 'pre-wrap' }}>
          <span className="gh-skill-hint-label">🧩 Задание</span>
          <p>{skill.content}</p>
        </div>
      )}
      {skill.image_url && (
        <div className="gh-skill-task-img-box">
          <img src={skill.image_url} alt="Задание" />
        </div>
      )}
      {!skill.content && !skill.image_url && <div className="gh-empty">Задание ещё не добавлено 🧩</div>}

      {hints.length > 0 && (
        <div className="gh-skill-hints">
          {hints.slice(0, shown).map((h, i) => (
            <div key={i} className="gh-skill-hint-box">
              <span className="gh-skill-hint-label">💡 Подсказка {i + 1}</span>
              <p>{h}</p>
            </div>
          ))}
          {shown < hints.length && (
            <button className="gh-btn sm blue" onClick={() => setShown(s => s + 1)}>
              💡 Показать подсказку {shown + 1} из {hints.length}
            </button>
          )}
        </div>
      )}

      {allHintsShown && hasAnswer && !gaveUp && (
        <button className="gh-btn sm" style={{ marginTop: 12 }} onClick={() => setGaveUp(true)}>
          🏳️ Сдаюсь
        </button>
      )}

      {gaveUp && (
        <div className="gh-skill-hint-box gh-skill-answer-box" style={{ marginTop: 12 }}>
          <span className="gh-skill-hint-label gh-skill-answer-label">✅ Правильный ответ</span>
          <p>{skill.answer}</p>
        </div>
      )}
    </div>
  )
}
