import { useState } from 'react'

// Показ одного задания «Навыков»: картинка + до 3 подсказок, открываемых по одной.
// key={skill.id} на месте использования сбрасывает состояние при смене задания.
export function SkillTaskView({ skill }) {
  const [shown, setShown] = useState(0)
  const hints = [skill.hint1, skill.hint2, skill.hint3].filter(h => h && h.trim())

  return (
    <div className="gh-skill-task">
      <div className="gh-skill-task-img-box">
        {skill.image_url
          ? <img src={skill.image_url} alt="Задание" />
          : <div className="gh-empty">Картинка ещё не загружена 🖼️</div>}
      </div>

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
    </div>
  )
}
