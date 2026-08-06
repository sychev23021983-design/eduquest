import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSettings } from '../context/SettingsContext.jsx'
import '../game-theme.css'
import '../mission-theme.css'

const INITIAL = {
  north: ['Создавать полезные вещи', 'Не сдаваться, когда трудно', 'Быстро учиться'],
  worlds: [
    ['🛠️', 'Мир инженера', 'Сделать 20 моделей в Fusion 360', 8, 20, '#3b82f6'],
    ['🔬', 'Мир исследователя', 'Прочитать 12 научных книг', 3, 12, '#14b8a6'],
    ['🧠', 'Мир логики', 'Решить 52 сложные задачи', 11, 52, '#8b5cf6'],
    ['🎨', 'Мир создателя', 'Создать собственную настольную игру', 2, 8, '#f97316'],
    ['🏃', 'Мир спортсмена', 'Научиться подтягиваться 10 раз', 4, 10, '#ef4444'],
    ['💡', 'Мир предпринимателя', 'Продать первую собственную 3D-модель', 0, 1, '#eab308'],
  ],
  week: ['Решить одну задачу на логику', 'Провести научный эксперимент', 'Сделать одну модель Fusion', 'Прочитать 30 страниц', 'Погулять с наблюдениями'],
  today: ['Сделать первый эскиз', 'Решить задачу недели', 'Прочитать 15 страниц'], energy: 'high',
}
const activities = { high: 'Математика · Fusion 360 · Шахматы · Исследования', medium: 'Чтение · LEGO · Редактирование проекта · Схемы', low: 'Прогулка · Раскрашивание · Настольная игра · Обсуждение дня' }
const MATERIALS = [
  ['🧰', 'Изобрети приспособление для рабочего стола', 'Создай полезную вещь из картона, LEGO или деталей конструктора. Сделай минимум две версии и протестируй финальную.', 'проектирование · прототипирование · настойчивость', '/mission-icons/toolbox.png'],
  ['🥚', 'Спаси яйцо', 'Сделай защитную конструкцию, чтобы яйцо пережило падение. Работай с ограничениями и спокойно анализируй неудачу.', 'планирование · ограничения · прототипирование', '/mission-icons/mountain.png'],
  ['🎈', 'Придумай машину, которая движется сама', 'Используй воздушный шар, резинку, магнит или наклонную плоскость: гипотеза, модель, испытание, изменение и объяснение.', 'гипотеза · инженерия · анализ ошибок', '/mission-icons/lightning.png'],
  ['🔢', 'Разгадай правило последовательности', 'Найди закономерность в числах, фигурах или символах, а затем придумай собственную задачу для другого человека.', 'логика · внимание · объяснение', '/mission-icons/brain.png'],
  ['📝', 'Найди ошибку в инструкции', 'Найди пропущенный шаг, противоречие, лишнее действие или неясную формулировку и перепиши инструкцию.', 'внимательность · точность · коммуникация', '/mission-icons/binoculars.png'],
  ['👨‍🏫', 'Научи младшего', 'Выбери знакомую тему и объясни её так, чтобы другой человек смог повторить действие без помощи.', 'объяснение · помощь · Active Recall', '/mission-icons/help.png'],
  ['🗓️', 'Освой навык за семь дней', 'Выбери небольшой навык. Каждый день пробуй, фиксируй трудность, меняй способ, повторяй и отмечай результат.', 'обучение · память · настойчивость', '/mission-icons/calendar.png'],
  ['🤝', 'Командная экспедиция', 'Работайте вместе. Распределите роли: исследователь, конструктор, испытатель, записчик результатов и рассказчик.', 'команда · договорённость · помощь', '/mission-icons/team.png'],
  ['🏆', 'Большой финальный проект', 'Выбери полезную вещь или задачу: игру, органайзер, машину, инструкцию, головоломку, модель или эксперимент.', 'все выбранные качества · самостоятельность', '/mission-icons/compass.png'],
]
const QUALITIES = [
  ['/mission-icons/brain.png', 'Решать сложные задачи', ['логика', 'математика', 'критическое мышление']],
  ['/mission-icons/toolbox.png', 'Создавать полезные вещи', ['проектирование', 'геометрия', 'прототипирование']],
  ['/mission-icons/research.png', 'Исследовать и находить ответы', ['наблюдение', 'эксперименты', 'поиск информации']],
  ['/mission-icons/palette.png', 'Придумывать новое', ['креативность', 'дизайн', 'сторителлинг']],
  ['/mission-icons/dialogue.png', 'Объяснять свои мысли', ['речь', 'письмо', 'презентации']],
  ['/mission-icons/help.png', 'Помогать другим', ['эмпатия', 'коммуникация', 'командная работа']],
  ['/mission-icons/mountain.png', 'Не сдаваться, когда трудно', ['саморегуляция', 'анализ ошибок', 'настойчивость']],
  ['/mission-icons/lightning.png', 'Быстро учиться', ['память', 'Active Recall', 'постановка вопросов']],
  ['/mission-icons/compass.png', 'Самостоятельно принимать решения', ['оценка вариантов', 'риски', 'ответственность']],
  ['/mission-icons/calendar.png', 'Планировать свои дела', ['декомпозиция', 'приоритеты', 'оценка времени']],
  ['/mission-icons/binoculars.png', 'Замечать важные детали', ['наблюдательность', 'точность', 'проверка ошибок']],
  ['/mission-icons/team.png', 'Работать в команде', ['слушание', 'переговоры', 'распределение ролей']],
]

export default function MissionPage() {
  const nav = useNavigate(); const { settings } = useSettings(); const [data, setData] = useState(INITIAL); const [tab, setTab] = useState('overview'); const [quality, setQuality] = useState(''); const [bridgeStep, setBridgeStep] = useState(0); const [bridgeNotes, setBridgeNotes] = useState({ prediction: '', result: '', change: '', improved: '', advice: '' })
  useEffect(() => { try { const x = localStorage.getItem('eduquest-mission'); if (x) { const saved = JSON.parse(x); const legacy = { 'умею создавать полезные вещи': 'Создавать полезные вещи', 'не боюсь трудностей': 'Не сдаваться, когда трудно', 'умею быстро учиться': 'Быстро учиться' }; saved.north = (saved.north || []).map(x => legacy[x] || x); setData({ ...INITIAL, ...saved }) } } catch {} }, [])
  useEffect(() => { localStorage.setItem('eduquest-mission', JSON.stringify(data)) }, [data])
  const bg = settings?.bg_main ? { backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed' } : {}
  const addQuality = e => { e.preventDefault(); if (!quality.trim()) return; setData(d => ({ ...d, north: [...d.north, quality.trim()] })); setQuality('') }
  const toggleQuality = name => setData(d => ({ ...d, north: d.north.includes(name) ? d.north.filter(x => x !== name) : d.north.length < 5 ? [...d.north, name] : d.north }))
  const selectedQualities = QUALITIES.filter(([, name]) => data.north.includes(name))
  const recommendedSkills = [...new Set(selectedQualities.flatMap(([, , skills]) => skills))]
  const toggle = i => setData(d => ({ ...d, today: d.today.map((x, n) => n === i ? x.startsWith('✅') ? x.slice(2) : `✅ ${x}` : x) }))
  return <div className="game-home mission-page" style={bg}>
    <div className="gh-topbar"><button className="gh-back-btn" onClick={() => nav('/')}>‹</button><div className="gh-map-title"><span className="gh-map-title-text">🧭 МИССИЯ</span></div></div>
    <div className="gh-wrap" style={{ maxWidth: 1120 }}>
      <div className="gh-hero" style={{ background: 'linear-gradient(120deg, rgba(27,75,140,.92), rgba(20,148,130,.86))' }}><div style={{ fontSize: 42 }}>🧭</div><h1>Моя миссия</h1><p>Не профессия. Путь человека, которым ты становишься.</p></div>
      <div className="gh-nav" style={{ margin: '18px 0', display: 'flex', gap: 6, flexWrap: 'wrap' }}>{[['overview','Обзор'],['materials','Материалы'],['week','Неделя'],['day','Сегодня'],['council','Совет исследователей']].map(([k, t]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{t}</button>)}</div>
      {tab === 'materials' && <section className="gh-card" style={{ marginTop: 18 }}><div className="gh-section-title">🧭 Другие экспедиции</div><p style={{ color: 'var(--gh-muted)' }}>Выбирай материал, который хочется попробовать. Здесь нет единственного правильного результата.</p><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 14 }}>{MATERIALS.map(([icon, title, description, skills, image]) => <article className="gh-card" key={title} style={{ padding: 0, overflow: 'hidden', background: '#162b4a' }}><img src={image} alt="" style={{ width: '100%', height: 120, objectFit: 'contain', background: '#102344', display: 'block' }} /><div style={{ padding: 16 }}><div style={{ fontSize: 30 }}>{icon}</div><h3 style={{ margin: '6px 0 8px' }}>{title}</h3><p style={{ color: 'var(--gh-muted)', fontSize: 14, minHeight: 74 }}>{description}</p><div className="gh-chip gem" style={{ fontSize: 12 }}>{skills}</div><button className="gh-btn blue" style={{ marginTop: 14, width: '100%' }} onClick={() => window.alert(`Экспедиция «${title}» будет открыта следующим шагом.`)}>Открыть материал →</button></div></article>)}</div></section>}
      {tab === 'overview' && <>
        <section className="gh-card" style={{ marginBottom: 18 }}><div className="gh-section-title">🌟 Каким человеком я хочу стать?</div><p style={{ color: 'var(--gh-muted)' }}>Выбери от 3 до 5 качеств. Это не профессия и не окончательное решение — выбор поможет подобрать подходящие навыки и проекты.</p><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, margin: '16px 0' }}>{QUALITIES.map(([icon, name]) => { const selected = data.north.includes(name); return <button key={name} onClick={() => toggleQuality(name)} style={{ textAlign: 'left', padding: 14, borderRadius: 12, border: `2px solid ${selected ? 'var(--gh-green)' : 'rgba(255,255,255,.12)'}`, background: selected ? 'rgba(34,211,139,.15)' : 'rgba(255,255,255,.05)', color: 'var(--gh-text)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}><img src={icon} alt="" style={{ width: 72, height: 72, objectFit: 'contain', flexShrink: 0 }} /><b>{name}</b>{selected && <span style={{ marginLeft: 'auto', color: 'var(--gh-green)', fontSize: 24 }}>✓</span>}</button> })}</div><div style={{ color: 'var(--gh-muted)', fontSize: 13 }}>Выбрано: {data.north.length} / 5{data.north.length >= 5 && ' · максимум выбран'}</div>{data.north.filter(x => !QUALITIES.some(([, name]) => name === x)).length > 0 && <form onSubmit={addQuality} style={{ display: 'flex', gap: 8, marginTop: 12 }}><input className="input" placeholder="Добавить своё качество" value={quality} onChange={e => setQuality(e.target.value)} /><button className="gh-btn blue">Добавить</button></form>}</section>
        {selectedQualities.length > 0 && <section className="gh-card" style={{ marginBottom: 18, background: 'rgba(20,184,166,.12)' }}><div className="gh-section-title">🧭 Твой профиль развития</div><p style={{ color: 'var(--gh-muted)' }}>Ты выбрал: {selectedQualities.map(([, name]) => name.toLowerCase()).join(' · ')}</p><b>Навыки, которые помогут:</b><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>{recommendedSkills.map(x => <span className="gh-chip gem" key={x}>{x}</span>)}</div><p style={{ color: 'var(--gh-muted)', marginBottom: 0, marginTop: 14 }}>Эти навыки будут попадать в блок «Для моей миссии» и влиять на предлагаемые проекты.</p></section>}
        <div className="gh-section-title">🗺️ Миры этого года</div><div className="gh-subjects-grid" style={{ marginBottom: 22 }}>{data.worlds.map(([icon, name, goal, done, total, color]) => <div className="gh-card" key={name} style={{ borderTop: `4px solid ${color}` }}><div style={{ fontSize: 36 }}>{icon}</div><h3 style={{ margin: '6px 0' }}>{name}</h3><p style={{ color: 'var(--gh-muted)', minHeight: 40 }}>{goal}</p><div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: `${done / total * 100}%`, background: color }} /></div><small>{done} / {total}</small></div>)}</div>
        <section className="gh-card"><div className="gh-section-title">🚀 Экспедиция квартала</div><h2>Создать полезную вещь в Fusion 360</h2><p style={{ color: 'var(--gh-muted)' }}>Текущий двигатель: <b>Сделать первый эскиз</b></p><div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: '30%' }} /></div><small>3 / 10 шагов</small></section>
      </>}
      {tab === 'materials' && <section className="gh-card">
        <div className="gh-section-title">🚀 Материалы для моей миссии</div>
        <p style={{ color: 'var(--gh-muted)' }}>Практические экспедиции, в которых нужно не выбрать ответ, а создать, испытать и улучшить результат.</p>
        <div className="gh-card" style={{ marginTop: 18, borderTop: '4px solid #3b82f6' }}>
          <div style={{ fontSize: 44 }}>🌉</div><h2>Построй самый прочный мост</h2>
          <p style={{ color: 'var(--gh-muted)' }}>Построй мост между двумя книгами и проверь, сколько монет он выдержит.</p>
          <img src="/mission-icons/bridge-types.png" alt="Типы мостов: балочный, арочный, ферменный и подвесной" style={{ width: '100%', borderRadius: 12, margin: '14px 0', display: 'block' }} />
          <p style={{ color: 'var(--gh-muted)', fontStyle: 'italic' }}>Посмотри на разные конструкции. Какую идею ты попробуешь первой?</p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '14px 0' }}><span className="gh-chip gem">🧠 Решение задач</span><span className="gh-chip gem">🛠 Создание вещей</span><span className="gh-chip gem">🧗 Настойчивость</span><span className="gh-chip gem">⚡ Быстрое обучение</span></div>
          <p><b>Время:</b> 45–60 минут · <b>Сложность:</b> ⭐⭐</p>
          {bridgeStep === 0 && <button className="gh-btn blue" onClick={() => setBridgeStep(1)}>Начать экспедицию →</button>}
        </div>
        {bridgeStep > 0 && <div style={{ marginTop: 18 }}>
          <div className="gh-card" style={{ background: '#123b49', marginBottom: 12 }}><div className="gh-section-title">1. Исследование</div><p>Перед тобой две книги, бумага, скотч и монеты. Как сделать мост прочным?</p><p><b>Предскажи:</b> где мост сломается первым?</p><textarea className="input" rows="2" placeholder="Моя гипотеза..." value={bridgeNotes.prediction} onChange={e => setBridgeNotes(n => ({ ...n, prediction: e.target.value }))} /></div>
          <div className="gh-card" style={{ marginBottom: 12 }}><div className="gh-section-title">2. Создай и испытай</div><p>Построй первую версию моста. Постепенно добавляй монеты и наблюдай, что происходит.</p><label>Сколько монет выдержала первая версия?</label><input className="input" type="number" min="0" value={bridgeNotes.result} onChange={e => setBridgeNotes(n => ({ ...n, result: e.target.value }))} style={{ marginTop: 8 }} /></div>
          <div className="gh-card" style={{ marginBottom: 12 }}><div className="gh-section-title">3. Улучши конструкцию</div><p>Что сломалось? Измени только одну деталь и проведи второе испытание.</p><textarea className="input" rows="2" placeholder="Я изменил..." value={bridgeNotes.change} onChange={e => setBridgeNotes(n => ({ ...n, change: e.target.value }))} /><label style={{ display: 'block', marginTop: 10 }}>Сколько монет выдержала улучшенная версия?</label><input className="input" type="number" min="0" value={bridgeNotes.improved} onChange={e => setBridgeNotes(n => ({ ...n, improved: e.target.value }))} style={{ marginTop: 8 }} /></div>
          <div className="gh-card" style={{ marginBottom: 12 }}><div className="gh-section-title">4. Объясни и помоги</div><p>Почему вторая версия оказалась лучше? Какой совет ты дашь другому строителю?</p><textarea className="input" rows="3" placeholder="Мой вывод и совет..." value={bridgeNotes.advice} onChange={e => setBridgeNotes(n => ({ ...n, advice: e.target.value }))} /></div>
          <button className="gh-btn blue" disabled={!bridgeNotes.result || !bridgeNotes.improved || !bridgeNotes.advice} onClick={() => setBridgeStep(2)}>{bridgeStep === 1 ? 'Завершить экспедицию →' : 'Экспедиция завершена ✓'}</button>
          {bridgeStep === 2 && <div className="gh-card" style={{ marginTop: 14, background: '#123b49' }}><h3>🎉 Результат сохранён</h3><p>Ты создал, испытал и улучшил конструкцию. Это и есть инженерный способ мышления.</p></div>}
        </div>}
      </section>}
      {tab === 'week' && <section className="gh-card"><div className="gh-section-title">📅 Пять шагов этой недели</div>{data.week.map((x, i) => <div className="gh-lesson-row" key={x}><span className="emoji">{['🧠','🔬','🛠️','📖','🌿'][i]}</span><div className="title">{x}</div><span>○</span></div>)}<p style={{ color: 'var(--gh-muted)', marginTop: 18 }}>Воскресенье — полностью свободный день.</p></section>}
      {tab === 'day' && <section className="gh-card"><div className="gh-section-title">☀️ Сегодня — три главных шага</div>{data.today.map((x, i) => <button key={i} onClick={() => toggle(i)} style={{ display: 'block', width: '100%', textAlign: 'left', background: 'transparent', border: 0, borderBottom: '1px solid rgba(255,255,255,.1)', padding: 15, color: x.startsWith('✅') ? 'var(--gh-green)' : 'var(--gh-text)', fontSize: 16 }}>{x.startsWith('✅') ? x : `□ ${x}`}</button>)}<div className="gh-section-title" style={{ marginTop: 24 }}>⚡ Сколько энергии?</div><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{[['high','Много'],['medium','Нормально'],['low','Мало']].map(([k, t]) => <button className={`gh-btn ${data.energy === k ? 'blue' : ''}`} key={k} onClick={() => setData(d => ({ ...d, energy: k }))}>{t}</button>)}</div><p style={{ color: 'var(--gh-muted)' }}>Подойдут: {activities[data.energy]}</p></section>}
      {tab === 'council' && <section className="gh-card"><div className="gh-section-title">🪨 Совет исследователей</div><p style={{ color: 'var(--gh-muted)' }}>Воскресный разговор без оценок и сравнения.</p>{['Что нового я узнал?', 'Что получилось?', 'Что было сложно?', 'Чем я горжусь?', 'Какой следующий шаг?'].map(q => <div className="gh-card" key={q} style={{ margin: '10px 0', background: 'rgba(255,255,255,.05)' }}><b>{q}</b><div style={{ height: 25, borderBottom: '1px dashed rgba(255,255,255,.25)', marginTop: 10 }} /></div>)}</section>}
    </div>
  </div>
}
