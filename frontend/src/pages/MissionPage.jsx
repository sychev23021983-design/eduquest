import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSettings } from '../context/SettingsContext.jsx'
import '../game-theme.css'

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
const QUALITIES = [
  ['🧠', 'Решать сложные задачи', ['логика', 'математика', 'критическое мышление']],
  ['🛠️', 'Создавать полезные вещи', ['проектирование', 'геометрия', 'прототипирование']],
  ['🔬', 'Исследовать и находить ответы', ['наблюдение', 'эксперименты', 'поиск информации']],
  ['🎨', 'Придумывать новое', ['креативность', 'дизайн', 'сторителлинг']],
  ['💬', 'Объяснять свои мысли', ['речь', 'письмо', 'презентации']],
  ['🤝', 'Помогать другим', ['эмпатия', 'коммуникация', 'командная работа']],
  ['🧗', 'Не сдаваться, когда трудно', ['саморегуляция', 'анализ ошибок', 'настойчивость']],
  ['⚡', 'Быстро учиться', ['память', 'Active Recall', 'постановка вопросов']],
  ['🧭', 'Самостоятельно принимать решения', ['оценка вариантов', 'риски', 'ответственность']],
  ['📅', 'Планировать свои дела', ['декомпозиция', 'приоритеты', 'оценка времени']],
  ['👀', 'Замечать важные детали', ['наблюдательность', 'точность', 'проверка ошибок']],
  ['🗣️', 'Работать в команде', ['слушание', 'переговоры', 'распределение ролей']],
]

export default function MissionPage() {
  const nav = useNavigate(); const { settings } = useSettings(); const [data, setData] = useState(INITIAL); const [tab, setTab] = useState('overview'); const [quality, setQuality] = useState('')
  useEffect(() => { try { const x = localStorage.getItem('eduquest-mission'); if (x) { const saved = JSON.parse(x); const legacy = { 'умею создавать полезные вещи': 'Создавать полезные вещи', 'не боюсь трудностей': 'Не сдаваться, когда трудно', 'умею быстро учиться': 'Быстро учиться' }; saved.north = (saved.north || []).map(x => legacy[x] || x); setData({ ...INITIAL, ...saved }) } } catch {} }, [])
  useEffect(() => { localStorage.setItem('eduquest-mission', JSON.stringify(data)) }, [data])
  const bg = settings?.bg_main ? { backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed' } : {}
  const addQuality = e => { e.preventDefault(); if (!quality.trim()) return; setData(d => ({ ...d, north: [...d.north, quality.trim()] })); setQuality('') }
  const toggleQuality = name => setData(d => ({ ...d, north: d.north.includes(name) ? d.north.filter(x => x !== name) : d.north.length < 5 ? [...d.north, name] : d.north }))
  const selectedQualities = QUALITIES.filter(([, name]) => data.north.includes(name))
  const recommendedSkills = [...new Set(selectedQualities.flatMap(([, , skills]) => skills))]
  const toggle = i => setData(d => ({ ...d, today: d.today.map((x, n) => n === i ? x.startsWith('✅') ? x.slice(2) : `✅ ${x}` : x) }))
  return <div className="game-home" style={bg}>
    <div className="gh-topbar"><button className="gh-back-btn" onClick={() => nav('/')}>‹</button><div className="gh-map-title"><span className="gh-map-title-text">🧭 МИССИЯ</span></div></div>
    <div className="gh-wrap" style={{ maxWidth: 1120 }}>
      <div className="gh-hero" style={{ background: 'linear-gradient(120deg, rgba(27,75,140,.92), rgba(20,148,130,.86))' }}><div style={{ fontSize: 42 }}>🧭</div><h1>Моя миссия</h1><p>Не профессия. Путь человека, которым ты становишься.</p></div>
      <div className="gh-nav" style={{ margin: '18px 0', display: 'flex', gap: 6, flexWrap: 'wrap' }}>{[['overview','Обзор'],['week','Неделя'],['day','Сегодня'],['council','Совет исследователей']].map(([k, t]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{t}</button>)}</div>
      {tab === 'overview' && <>
        <section className="gh-card" style={{ marginBottom: 18 }}><div className="gh-section-title">🌟 Каким человеком я хочу стать?</div><p style={{ color: 'var(--gh-muted)' }}>Выбери от 3 до 5 качеств. Это не профессия и не окончательное решение — выбор поможет подобрать подходящие навыки и проекты.</p><div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10, margin: '16px 0' }}>{QUALITIES.map(([icon, name]) => { const selected = data.north.includes(name); return <button key={name} onClick={() => toggleQuality(name)} style={{ textAlign: 'left', padding: 14, borderRadius: 12, border: `2px solid ${selected ? 'var(--gh-green)' : 'rgba(255,255,255,.12)'}`, background: selected ? 'rgba(34,211,139,.15)' : 'rgba(255,255,255,.05)', color: 'var(--gh-text)', cursor: 'pointer' }}><span style={{ fontSize: 24, marginRight: 8 }}>{icon}</span><b>{name}</b>{selected && <span style={{ float: 'right', color: 'var(--gh-green)' }}>✓</span>}</button> })}</div><div style={{ color: 'var(--gh-muted)', fontSize: 13 }}>Выбрано: {data.north.length} / 5{data.north.length >= 5 && ' · максимум выбран'}</div>{data.north.filter(x => !QUALITIES.some(([, name]) => name === x)).length > 0 && <form onSubmit={addQuality} style={{ display: 'flex', gap: 8, marginTop: 12 }}><input className="input" placeholder="Добавить своё качество" value={quality} onChange={e => setQuality(e.target.value)} /><button className="gh-btn blue">Добавить</button></form>}</section>
        {selectedQualities.length > 0 && <section className="gh-card" style={{ marginBottom: 18, background: 'rgba(20,184,166,.12)' }}><div className="gh-section-title">🧭 Твой профиль развития</div><p style={{ color: 'var(--gh-muted)' }}>Ты выбрал: {selectedQualities.map(([, name]) => name.toLowerCase()).join(' · ')}</p><b>Навыки, которые помогут:</b><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>{recommendedSkills.map(x => <span className="gh-chip gem" key={x}>{x}</span>)}</div><p style={{ color: 'var(--gh-muted)', marginBottom: 0, marginTop: 14 }}>Эти навыки будут попадать в блок «Для моей миссии» и влиять на предлагаемые проекты.</p></section>}
        <div className="gh-section-title">🗺️ Миры этого года</div><div className="gh-subjects-grid" style={{ marginBottom: 22 }}>{data.worlds.map(([icon, name, goal, done, total, color]) => <div className="gh-card" key={name} style={{ borderTop: `4px solid ${color}` }}><div style={{ fontSize: 36 }}>{icon}</div><h3 style={{ margin: '6px 0' }}>{name}</h3><p style={{ color: 'var(--gh-muted)', minHeight: 40 }}>{goal}</p><div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: `${done / total * 100}%`, background: color }} /></div><small>{done} / {total}</small></div>)}</div>
        <section className="gh-card"><div className="gh-section-title">🚀 Экспедиция квартала</div><h2>Создать полезную вещь в Fusion 360</h2><p style={{ color: 'var(--gh-muted)' }}>Текущий двигатель: <b>Сделать первый эскиз</b></p><div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: '30%' }} /></div><small>3 / 10 шагов</small></section>
      </>}
      {tab === 'week' && <section className="gh-card"><div className="gh-section-title">📅 Пять шагов этой недели</div>{data.week.map((x, i) => <div className="gh-lesson-row" key={x}><span className="emoji">{['🧠','🔬','🛠️','📖','🌿'][i]}</span><div className="title">{x}</div><span>○</span></div>)}<p style={{ color: 'var(--gh-muted)', marginTop: 18 }}>Воскресенье — полностью свободный день.</p></section>}
      {tab === 'day' && <section className="gh-card"><div className="gh-section-title">☀️ Сегодня — три главных шага</div>{data.today.map((x, i) => <button key={i} onClick={() => toggle(i)} style={{ display: 'block', width: '100%', textAlign: 'left', background: 'transparent', border: 0, borderBottom: '1px solid rgba(255,255,255,.1)', padding: 15, color: x.startsWith('✅') ? 'var(--gh-green)' : 'var(--gh-text)', fontSize: 16 }}>{x.startsWith('✅') ? x : `□ ${x}`}</button>)}<div className="gh-section-title" style={{ marginTop: 24 }}>⚡ Сколько энергии?</div><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{[['high','Много'],['medium','Нормально'],['low','Мало']].map(([k, t]) => <button className={`gh-btn ${data.energy === k ? 'blue' : ''}`} key={k} onClick={() => setData(d => ({ ...d, energy: k }))}>{t}</button>)}</div><p style={{ color: 'var(--gh-muted)' }}>Подойдут: {activities[data.energy]}</p></section>}
      {tab === 'council' && <section className="gh-card"><div className="gh-section-title">🪨 Совет исследователей</div><p style={{ color: 'var(--gh-muted)' }}>Воскресный разговор без оценок и сравнения.</p>{['Что нового я узнал?', 'Что получилось?', 'Что было сложно?', 'Чем я горжусь?', 'Какой следующий шаг?'].map(q => <div className="gh-card" key={q} style={{ margin: '10px 0', background: 'rgba(255,255,255,.05)' }}><b>{q}</b><div style={{ height: 25, borderBottom: '1px dashed rgba(255,255,255,.25)', marginTop: 10 }} /></div>)}</section>}
    </div>
  </div>
}
