import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import '../game-theme.css'

const SUBJ = { math: 'Математика', russian: 'Русский язык', science: 'Окружающий мир', history: 'История' }
const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }
const SUBJ_KEY  = ['math', 'russian', 'science', 'history']
const XP_PER_LEVEL = 300

function SubjectIcon({ subj, icons, size = 28 }) {
  const custom = icons?.[subj]
  if (custom) return <img src={custom} alt="" style={{ width: size, height: size, objectFit: 'contain' }} />
  return <span style={{ fontSize: size }}>{SUBJ_ICON[subj]}</span>
}

export default function ChildHome() {
  const { logout, token } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [lessons, setLessons]   = useState([])
  const [stats,   setStats]     = useState(null)
  const [balance, setBalance]   = useState({ balance: 0, earned: 0, spent: 0 })
  const [rewards, setRewards]   = useState([])
  const [config,  setConfig]    = useState({ child_name: '' })
  const [rewardName, setRName]  = useState('')
  const [rewardCost, setRCost]  = useState(50)
  const [tab, setTab]           = useState('home')
  const [msg, setMsg]           = useState('')

  useEffect(() => { load() }, [])

  async function load() {
    const [ls, st, bl, rw, cfg] = await Promise.all([
      api.lessons(token), api.stats(token), api.balance(token), api.rewards(token), api.config()
    ])
    setLessons(ls); setStats(st); setBalance(bl); setRewards(rw); setConfig(cfg)
  }

  async function requestReward() {
    if (!rewardName.trim()) return
    try {
      await api.requestReward(token, { name: rewardName.trim(), cost_coins: Number(rewardCost) })
      setMsg('Запрос отправлен! Ждём одобрения 👍'); setRName('')
      load()
    } catch (e) { setMsg(e.message) }
    setTimeout(() => setMsg(''), 3000)
  }

  const pending = rewards.filter(r => r.status === 'pending')
  const streak  = stats?.streak_days || 0
  const xp      = balance.earned || 0
  const level   = Math.floor(xp / XP_PER_LEVEL) + 1
  const xpInLvl = xp % XP_PER_LEVEL
  const subjAvg = s => { const row = stats?.by_subject?.find(x => x.subject === s); return row ? Math.round(row.avg * 100) : null }

  if (!settings) return <div className="game-home"><div className="gh-wrap gh-empty">Загрузка…</div></div>

  const hasLeft  = !!settings.sidebar_left_url
  const hasRight = !!settings.sidebar_right_url
  const gridCols = '220px 1fr 220px'
  const gridAreas = hasLeft && hasRight
    ? `"img main info" "stats main rightimg"`
    : hasLeft && !hasRight
    ? `"img main info" "stats main info"`
    : !hasLeft && hasRight
    ? `"stats main info" "stats main rightimg"`
    : `"stats main info"`
  const gridRows = (hasLeft || hasRight) ? 'auto auto' : 'auto'

  const rootStyle = settings.bg_main ? {
    backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}
  const heroStyle = settings.bg_hero ? {
    backgroundImage: `linear-gradient(120deg, rgba(42,58,143,.72), rgba(138,58,168,.72)), url(${settings.bg_hero})`,
    backgroundSize: 'cover', backgroundPosition: 'center',
  } : {}
  const lodStyle = settings.bg_lesson_of_day ? {
    backgroundImage: `linear-gradient(120deg, rgba(26,58,107,.72), rgba(20,122,143,.72)), url(${settings.bg_lesson_of_day})`,
    backgroundSize: 'cover', backgroundPosition: 'center',
  } : {}

  return (
    <div className="game-home" style={rootStyle}>
      {/* Top bar */}
      <div className="gh-topbar">
        {settings.logo_url ? (
          <img src={settings.logo_url} alt={settings.site_name} style={{ height: settings.logo_size || 28, objectFit: 'contain' }} />
        ) : (
          <span className="gh-logo">🕹️ {settings.site_name || 'EduQuest'}</span>
        )}
        <div className="gh-nav">
          {[['home','🏠 Главная'],['progress','📊 Прогресс'],['shop','🎁 Награды']].map(([k,l]) => (
            <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>
          ))}
        </div>
        <span className="gh-coin-pill">🪙 {balance.balance || 0}</span>
        <button className="gh-logout" onClick={logout}>Выйти</button>
      </div>

      <div className="gh-shell" style={{ gridTemplateColumns: gridCols, gridTemplateRows: gridRows, gridTemplateAreas: gridAreas }}>
        {hasLeft && (
          <img className="gh-panel-img gh-img-area" src={settings.sidebar_left_url} alt="" />
        )}

        <div className="gh-stats-area">
          <div className="gh-stat-card">
            <div className="gh-stat-label">Твой уровень</div>
            <div className="gh-level-badge">{level}</div>
            <div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: `${(xpInLvl / XP_PER_LEVEL) * 100}%` }} /></div>
            <div className="gh-xp-label">{xpInLvl} / {XP_PER_LEVEL} XP</div>
          </div>
          <div className="gh-stat-card">
            <div className="gh-stat-label">Серия дней</div>
            <div style={{ fontSize: '1.8rem', fontFamily: 'var(--font-num)', fontWeight: 800 }}>🔥 {streak}</div>
            <div className="gh-xp-label">дней подряд</div>
          </div>
          <div className="gh-stat-card">
            <div className="gh-stat-label">Пройдено уроков</div>
            <div style={{ fontSize: '1.8rem', fontFamily: 'var(--font-num)', fontWeight: 800 }}>📚 {stats?.total_lessons || 0}</div>
            <div className="gh-xp-label">всего попыток</div>
          </div>
        </div>

        <div className="gh-wrap gh-main-area">

          {/* HOME TAB */}
          {tab === 'home' && <>
            <div className="gh-hero" style={heroStyle}>
              <h1>Привет, {config.child_name || 'исследователь'}! 👋</h1>
              <p>Учись, зарабатывай монеты и открывай новые темы!</p>
              {streak > 0 && (
                <div className="gh-streak-chip">🔥 {streak} {streak === 1 ? 'день' : 'дня'} подряд — не останавливайся!</div>
              )}
            </div>

            {lessons.length > 0 && (
              <div className="gh-lod" style={lodStyle}>
                <div className="gh-lod-label">⭐ УРОК ДНЯ</div>
                <span className={`gh-badge ${lessons[0].subject}`}>{SUBJ[lessons[0].subject]}</span>
                <h2>{lessons[0].topic}</h2>
                <div className="gh-lod-meta">
                  <span className="gh-chip coin">🪙 +{lessons[0].coins_lesson} монет</span>
                  <span className="gh-chip gem">💎 +{lessons[0].coins_boss} за финал</span>
                </div>
                <button className="gh-btn" onClick={() => nav(`/lesson/${lessons[0].id}`)}>Начать урок →</button>
              </div>
            )}

            {/* Subjects grid */}
            <div className="gh-section-title">Предметы</div>
            <div className="gh-subjects-grid">
              {SUBJ_KEY.map(s => {
                const subLessons = lessons.filter(l => l.subject === s)
                const avg = subjAvg(s)
                return (
                  <div key={s} className={`gh-subject-card ${s}`} onClick={() => nav(`/subject/${s}`)}>
                    <div className="icon"><SubjectIcon subj={s} icons={settings.subject_icons} size={30} /></div>
                    <div className="name">{SUBJ[s]}</div>
                    <div className="count">{subLessons.length} {subLessons.length === 1 ? 'урок' : 'уроков'}{avg !== null ? ` · ${avg}%` : ''}</div>
                  </div>
                )
              })}
            </div>

            {/* Нужно повторить */}
            <div className="gh-section-title">⚠️ Нужно повторить</div>
            <div>
              {(stats?.weak_topics || []).map(t => (
                <div key={t.lesson_id} className="gh-lesson-row" onClick={() => nav(`/lesson/${t.lesson_id}`)}>
                  <span className="emoji"><SubjectIcon subj={t.subject} icons={settings.subject_icons} size={24} /></span>
                  <div style={{ flex: 1 }}>
                    <span className={`gh-badge ${t.subject}`}>{SUBJ[t.subject]}</span>
                    <div className="title">{t.topic}</div>
                  </div>
                  <span style={{ fontFamily: 'var(--font-num)', fontWeight: 700, color: 'var(--gh-red)', fontSize: '0.85rem' }}>{Math.round(t.avg * 100)}%</span>
                  <span style={{ color: 'var(--gh-blue)', fontSize: 20 }}>›</span>
                </div>
              ))}
              {(!stats?.weak_topics || stats.weak_topics.length === 0) && (
                <div className="gh-card gh-empty">Пока нечего повторять — все темы даются хорошо! 🎉</div>
              )}
            </div>
          </>}

          {/* PROGRESS TAB */}
          {tab === 'progress' && stats && (
            <div>
              <div className="gh-stats-row">
                {[
                  ['Уроков', stats.total_lessons, '📚'],
                  ['Монет', balance.balance || 0, '🪙'],
                  ['Серия', stats.streak_days + ' дн.', '🔥'],
                ].map(([l, v, i]) => (
                  <div key={l} className="gh-stat-card" style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 26 }}>{i}</div>
                    <div style={{ fontSize: 22, fontWeight: 800, marginTop: 4, fontFamily: 'var(--font-num)' }}>{v}</div>
                    <div className="gh-xp-label">{l}</div>
                  </div>
                ))}
              </div>

              <div className="gh-section-title">По предметам</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
                {stats.by_subject.map(s => (
                  <div key={s.subject} className="gh-card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <SubjectIcon subj={s.subject} icons={settings.subject_icons} size={20} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 700, marginBottom: 6 }}>{SUBJ[s.subject]}</div>
                      <div className="gh-xp-track"><div className="gh-xp-fill" style={{ width: `${Math.round(s.avg * 100)}%` }} /></div>
                    </div>
                    <span style={{ fontSize: 14, color: 'var(--gh-muted)', width: 44, textAlign: 'right', fontFamily: 'var(--font-num)' }}>{Math.round(s.avg * 100)}%</span>
                  </div>
                ))}
                {stats.by_subject.length === 0 && <div className="gh-card gh-empty">Пройди первый урок, чтобы увидеть прогресс</div>}
              </div>

              {stats.weak_topics.length > 0 && <>
                <div className="gh-section-title" style={{ color: 'var(--gh-amber)' }}>⚠️ Нужно повторить</div>
                {stats.weak_topics.map(t => (
                  <div key={t.topic} className="gh-card" style={{ borderLeft: '3px solid var(--gh-amber)', marginBottom: 8 }}>
                    <span className={`gh-badge ${t.subject}`}>{SUBJ[t.subject]}</span>
                    <div style={{ fontWeight: 700, marginTop: 4 }}>{t.topic}</div>
                    <div className="gh-xp-label">Результат: {Math.round(t.avg * 100)}%</div>
                  </div>
                ))}
              </>}
            </div>
          )}

          {/* SHOP TAB */}
          {tab === 'shop' && (
            <div>
              <div className="gh-card" style={{ marginBottom: 20, textAlign: 'center' }}>
                <div style={{ fontSize: 34 }}>🪙</div>
                <div style={{ fontSize: 28, fontWeight: 800, marginTop: 4, fontFamily: 'var(--font-num)' }}>{balance.balance || 0}</div>
                <div className="gh-xp-label">монет на балансе</div>
              </div>

              <div className="gh-card" style={{ marginBottom: 20 }}>
                <div style={{ fontWeight: 800, marginBottom: 14 }}>Запросить награду</div>
                <input className="input" placeholder="Название (например: 60 мин Roblox)"
                       value={rewardName} onChange={e => setRName(e.target.value)}
                       style={{ marginBottom: 10 }} />
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 14 }}>
                  <label style={{ fontSize: 14, color: 'var(--gh-muted)', whiteSpace: 'nowrap' }}>Стоимость монет:</label>
                  <input className="input" type="number" min="10" max={balance.balance} value={rewardCost}
                         onChange={e => setRCost(e.target.value)} />
                </div>
                {msg && <p style={{ fontSize: 14, color: rewardCost > balance.balance ? 'var(--gh-red)' : 'var(--gh-green)', marginBottom: 10 }}>{msg}</p>}
                <button className="gh-btn blue" style={{ width: '100%', justifyContent: 'center' }} onClick={requestReward}>
                  Отправить запрос родителю
                </button>
              </div>

              {pending.length > 0 && (
                <div>
                  <div className="gh-section-title">Ожидают одобрения</div>
                  {pending.map(r => (
                    <div key={r.id} className="gh-card" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontWeight: 700 }}>{r.name}</div>
                        <div className="gh-xp-label">{r.cost_coins} монет</div>
                      </div>
                      <span style={{ background: 'rgba(255,201,77,0.15)', color: 'var(--gh-amber)', borderRadius: 6, padding: '3px 10px', fontSize: 12 }}>⏳ Ждём</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="gh-section-title" style={{ marginTop: 20 }}>История наград</div>
              {rewards.filter(r => r.status !== 'pending').map(r => (
                <div key={r.id} className="gh-card" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{r.name}</div>
                    <div className="gh-xp-label">{r.cost_coins} монет</div>
                  </div>
                  <span style={{
                    borderRadius: 6, padding: '3px 10px', fontSize: 12,
                    background: r.status === 'approved' ? 'rgba(34,211,139,0.15)' : 'rgba(255,93,122,0.15)',
                    color: r.status === 'approved' ? 'var(--gh-green)' : 'var(--gh-red)',
                  }}>
                    {r.status === 'approved' ? '✅ Одобрено' : '❌ Отклонено'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="gh-info-area">
          <div className="gh-today-card">
            <h3>Сегодня ты можешь:</h3>
            <div className="gh-today-item"><span className="gh-today-check">✓</span> Пройти урок дня</div>
            <div className="gh-today-item"><span className="gh-today-check">✓</span> Заработать монеты</div>
            <div className="gh-today-item"><span className="gh-today-check">✓</span> Открыть новое знание</div>
            <div className="gh-today-item"><span className="gh-today-gift">🎁</span> Получить награду</div>
          </div>
        </div>
        {hasRight && <img className="gh-panel-img gh-right-area" src={settings.sidebar_right_url} alt="" />}
      </div>
    </div>
  )
}
