import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSettings } from '../context/SettingsContext.jsx'
import '../game-theme.css'

const INITIAL = {
  north: ['умею создавать полезные вещи', 'не боюсь трудностей', 'умею быстро учиться'],
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

export default function MissionPage() {
  const nav = useNavigate(); const { settings } = useSettings(); const [data, setData] = useState(INITIAL); const [tab, setTab] = useState('overview'); const [quality, setQuality] = useState('')
  useEffect(() => { try { const x = localStorage.getItem('eduquest-mission'); if (x) setData({ ...INITIAL, ...JSON.parse(x) }) } catch {} }, [])
  useEffect(() => { localStorage.setItem('eduquest-mission', JSON.stringify(data)) }, [data])
  const bg = settings?.bg_main ? { backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed' } : {}
  const addQuality = e => { e.preventDefault(); if (!quality.trim()) return; setData(d => ({ ...d, north: [...d.north, quality.trim()] })); setQuality('') }
  const toggle = i => setData(d => ({ ...d, today: d.today.map((x, n) => n === i ? x.startsWith('✅') ? x.slice(2) : `✅ ${x}` : x) }))
  return <div className="game-home" style={bg}>
    <div className="gh-topbar"><button className="gh-back-btn" onClick={() => nav('/')}>‹</button><div className="gh-map-title"><span className="gh-map-title-text">🧭 МИССИЯ</span></div></div>
    <div className="gh-wrap" style={{ maxWidth: 1120 }}>
      <div className="gh-hero" style={{ background: 'linear-gradient(120deg, rgba(27,75,140,.92), rgba(20,148,130,.86))' }}><div style={{ fontSize: 42 }}>🧭</div><h1>Моя миссия</h1><p>Не профессия. Путь человека, которым ты становишься.</p></div>
      <div className="gh-nav" style={{ margin: '18px 0', display: 'flex', gap: 6, flexWrap: 'wrap' }}>{[['overview','Обзор'],['week','Неделя'],['day','Сегодня'],['council','Совет исследователей']].map(([k, t]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{t}</button>)}</div>
      {tab === 'overview' && <>
        <section className="gh-card" style={{ marginBottom: 18 }}><div className="gh-section-title">🌟 Мой север</div><p style={{ color: 'var(--gh-muted)' }}>Каким человеком я становлюсь?</p><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>{data.north.map(x => <span className="gh-chip gem" key={x}>{x}</span>)}</div><form onSubmit={addQuality} style={{ display: 'flex', gap: 8 }}><input className="input" placeholder="Добавить качество" value={quality} onChange={e => setQuality(e.target.value)} /><button className="gh-btn blue">Добавить</button></form></section>
        <div className="gh-section-title">🗺️ Миры этого года</div><div className="gh-subjects-grid" style={{ marginBottom: 22 }}>{data.worlds.map(([icon, name, goal, done, total, color]) => <div className="gh-card" key={name} style={{ borderTop: `4px solid ${color}` }}><div style={{ fontSize: 36 }}>{icon}</div><h3 style={{ margin: '6px 0' }}>{name}</h3><p style={{ color: 'var(--gh-muted)', minHeight: 40 }}>{goal}</p><div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: `${done / total * 100}%`, background: color }} /></div><small>{done} / {total}</small></div>)}</div>
        <section className="gh-card"><div className="gh-section-title">🚀 Экспедиция квартала</div><h2>Создать полезную вещь в Fusion 360</h2><p style={{ color: 'var(--gh-muted)' }}>Текущий двигатель: <b>Сделать первый эскиз</b></p><div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: '30%' }} /></div><small>3 / 10 шагов</small></section>
      </>}
      {tab === 'week' && <section className="gh-card"><div className="gh-section-title">📅 Пять шагов этой недели</div>{data.week.map((x, i) => <div className="gh-lesson-row" key={x}><span className="emoji">{['🧠','🔬','🛠️','📖','🌿'][i]}</span><div className="title">{x}</div><span>○</span></div>)}<p style={{ color: 'var(--gh-muted)', marginTop: 18 }}>Воскресенье — полностью свободный день.</p></section>}
      {tab === 'day' && <section className="gh-card"><div className="gh-section-title">☀️ Сегодня — три главных шага</div>{data.today.map((x, i) => <button key={i} onClick={() => toggle(i)} style={{ display: 'block', width: '100%', textAlign: 'left', background: 'transparent', border: 0, borderBottom: '1px solid rgba(255,255,255,.1)', padding: 15, color: x.startsWith('✅') ? 'var(--gh-green)' : 'var(--gh-text)', fontSize: 16 }}>{x.startsWith('✅') ? x : `□ ${x}`}</button>)}<div className="gh-section-title" style={{ marginTop: 24 }}>⚡ Сколько энергии?</div><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{[['high','Много'],['medium','Нормально'],['low','Мало']].map(([k, t]) => <button className={`gh-btn ${data.energy === k ? 'blue' : ''}`} key={k} onClick={() => setData(d => ({ ...d, energy: k }))}>{t}</button>)}</div><p style={{ color: 'var(--gh-muted)' }}>Подойдут: {activities[data.energy]}</p></section>}
      {tab === 'council' && <section className="gh-card"><div className="gh-section-title">🪨 Совет исследователей</div><p style={{ color: 'var(--gh-muted)' }}>Воскресный разговор без оценок и сравнения.</p>{['Что нового я узнал?', 'Что получилось?', 'Что было сложно?', 'Чем я горжусь?', 'Какой следующий шаг?'].map(q => <div className="gh-card" key={q} style={{ margin: '10px 0', background: 'rgba(255,255,255,.05)' }}><b>{q}</b><div style={{ height: 25, borderBottom: '1px dashed rgba(255,255,255,.25)', marginTop: 10 }} /></div>)}</section>}
    </div>
  </div>
}
