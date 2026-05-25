import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'

const SUBJ = { math: 'Математика', russian: 'Русский язык', science: 'Окружающий мир', history: 'История' }
const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }
const SUBJ_KEY  = ['math', 'russian', 'science', 'history']

export default function ChildHome() {
  const { token, logout } = useAuth()
  const nav = useNavigate()
  const [lessons, setLessons]   = useState([])
  const [stats,   setStats]     = useState(null)
  const [balance, setBalance]   = useState(0)
  const [rewards, setRewards]   = useState([])
  const [rewardName, setRName]  = useState('')
  const [rewardCost, setRCost]  = useState(50)
  const [tab, setTab]           = useState('home')
  const [msg, setMsg]           = useState('')

  useEffect(() => { load() }, [])

  async function load() {
    const [ls, st, bl, rw] = await Promise.all([
      api.lessons(token), api.stats(token), api.balance(token), api.rewards(token)
    ])
    setLessons(ls); setStats(st); setBalance(bl.balance); setRewards(rw)
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

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      {/* Top bar */}
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>🎓 EduQuest</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ background: '#faeeda', color: '#7a4a00', borderRadius: 20, padding: '4px 12px', fontSize: 13, fontWeight: 600 }}>
            🪙 {balance} монет
          </span>
          <button onClick={logout} style={{ background: 'none', border: 'none', color: '#aaa', fontSize: 13 }}>Выйти</button>
        </div>
      </div>

      {/* Nav tabs */}
      <div style={{ background: '#fff', borderBottom: '1px solid var(--border)', display: 'flex', gap: 0 }}>
        {[['home','🏠 Главная'],['progress','📊 Прогресс'],['shop','🎁 Награды']].map(([k,l]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: '12px 20px', border: 'none', background: 'none', fontWeight: tab === k ? 600 : 400,
            color: tab === k ? 'var(--blue)' : 'var(--muted)', borderBottom: tab === k ? '2px solid var(--blue)' : '2px solid transparent',
            fontSize: 14
          }}>{l}</button>
        ))}
      </div>

      <div className="page">
        {/* HOME TAB */}
        {tab === 'home' && <>
          {/* Streak */}
          {streak > 0 && (
            <div style={{ background: 'var(--green-light)', border: '1px solid #86efac', borderRadius: 12, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
              <span style={{ fontSize: 28 }}>🔥</span>
              <div>
                <div style={{ fontWeight: 700, color: 'var(--green)' }}>{streak} дней подряд!</div>
                <div style={{ fontSize: 13, color: '#15803d' }}>Отличная серия, продолжай!</div>
              </div>
            </div>
          )}

          {/* Today's lesson */}
          {lessons.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: 'var(--muted)' }}>УРОК ДНЯ</h2>
              <div className="card" style={{ borderLeft: '4px solid var(--blue)', cursor: 'pointer' }}
                   onClick={() => nav(`/lesson/${lessons[0].id}`)}>
                <span className={`badge badge-${lessons[0].subject}`}>{SUBJ[lessons[0].subject]}</span>
                <h3 style={{ fontSize: 17, fontWeight: 600, margin: '8px 0 4px' }}>{lessons[0].topic}</h3>
                <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 12 }}>
                  Контекст: {lessons[0].context_theme === 'minecraft' ? '⛏️ Minecraft' : '🎮 ' + lessons[0].context_theme}
                </p>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: 13, color: 'var(--green)', fontWeight: 500 }}>+{lessons[0].coins_lesson} монет за урок · +{lessons[0].coins_boss} за босса</span>
                  <button className="btn btn-primary btn-sm">Начать →</button>
                </div>
              </div>
            </div>
          )}

          {/* Subjects grid */}
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: 'var(--muted)' }}>ПРЕДМЕТЫ</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 24 }}>
            {SUBJ_KEY.map(s => {
              const subLessons = lessons.filter(l => l.subject === s)
              return (
                <div key={s} className="card" style={{ cursor: 'pointer' }}
                     onClick={() => { /* filter tab */ }}>
                  <div style={{ fontSize: 28, marginBottom: 6 }}>{SUBJ_ICON[s]}</div>
                  <div style={{ fontWeight: 600 }}>{SUBJ[s]}</div>
                  <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>{subLessons.length} уроков</div>
                </div>
              )
            })}
          </div>

          {/* All lessons */}
          <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: 'var(--muted)' }}>ВСЕ УРОКИ</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {lessons.map(l => (
              <div key={l.id} className="card" style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 14 }}
                   onClick={() => nav(`/lesson/${l.id}`)}>
                <span style={{ fontSize: 24 }}>{SUBJ_ICON[l.subject]}</span>
                <div style={{ flex: 1 }}>
                  <span className={`badge badge-${l.subject}`} style={{ marginBottom: 2 }}>{SUBJ[l.subject]}</span>
                  <div style={{ fontWeight: 500 }}>{l.topic}</div>
                </div>
                <span style={{ fontSize: 13, color: 'var(--muted)', whiteSpace: 'nowrap' }}>🪙 {l.coins_lesson}</span>
                <span style={{ color: 'var(--blue)', fontSize: 20 }}>›</span>
              </div>
            ))}
            {lessons.length === 0 && <p style={{ color: 'var(--muted)', textAlign: 'center', padding: 40 }}>Уроки скоро появятся 🚀</p>}
          </div>
        </>}

        {/* PROGRESS TAB */}
        {tab === 'progress' && stats && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 24 }}>
              {[
                ['Уроков', stats.total_lessons, '📚'],
                ['Монет', balance, '🪙'],
                ['Серия', stats.streak_days + ' дн.', '🔥'],
              ].map(([l, v, i]) => (
                <div key={l} className="card" style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 28 }}>{i}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{v}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{l}</div>
                </div>
              ))}
            </div>

            <h3 style={{ marginBottom: 12, fontWeight: 600 }}>По предметам</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
              {stats.by_subject.map(s => (
                <div key={s.subject} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 20 }}>{SUBJ_ICON[s.subject]}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 500, marginBottom: 4 }}>{SUBJ[s.subject]}</div>
                    <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', background: 'var(--blue)', width: `${Math.round(s.avg * 100)}%`, borderRadius: 3 }} />
                    </div>
                  </div>
                  <span style={{ fontSize: 14, color: 'var(--muted)', width: 40, textAlign: 'right' }}>{Math.round(s.avg * 100)}%</span>
                </div>
              ))}
            </div>

            {stats.weak_topics.length > 0 && <>
              <h3 style={{ marginBottom: 12, fontWeight: 600, color: 'var(--amber)' }}>⚠️ Нужно повторить</h3>
              {stats.weak_topics.map(t => (
                <div key={t.topic} className="card" style={{ borderLeft: '3px solid var(--amber)', marginBottom: 8 }}>
                  <span className={`badge badge-${t.subject}`}>{SUBJ[t.subject]}</span>
                  <div style={{ fontWeight: 500, marginTop: 4 }}>{t.topic}</div>
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>Результат: {Math.round(t.avg * 100)}%</div>
                </div>
              ))}
            </>}
          </div>
        )}

        {/* SHOP TAB */}
        {tab === 'shop' && (
          <div>
            <div className="card" style={{ marginBottom: 20, textAlign: 'center' }}>
              <div style={{ fontSize: 36 }}>🪙</div>
              <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{balance}</div>
              <div style={{ color: 'var(--muted)', fontSize: 14 }}>монет на балансе</div>
            </div>

            <div className="card" style={{ marginBottom: 20 }}>
              <h3 style={{ fontWeight: 600, marginBottom: 14 }}>Запросить награду</h3>
              <input className="input" placeholder="Название (например: 60 мин Roblox)"
                     value={rewardName} onChange={e => setRName(e.target.value)}
                     style={{ marginBottom: 10 }} />
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 14 }}>
                <label style={{ fontSize: 14, color: 'var(--muted)', whiteSpace: 'nowrap' }}>Стоимость монет:</label>
                <input className="input" type="number" min="10" max={balance} value={rewardCost}
                       onChange={e => setRCost(e.target.value)} />
              </div>
              {msg && <p style={{ fontSize: 14, color: rewardCost > balance ? 'var(--red)' : 'var(--green)', marginBottom: 10 }}>{msg}</p>}
              <button className="btn btn-primary" onClick={requestReward} style={{ width: '100%', justifyContent: 'center' }}>
                Отправить запрос родителю
              </button>
            </div>

            {pending.length > 0 && (
              <div>
                <h3 style={{ fontWeight: 600, marginBottom: 12 }}>Ожидают одобрения</h3>
                {pending.map(r => (
                  <div key={r.id} className="card" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontWeight: 500 }}>{r.name}</div>
                      <div style={{ fontSize: 13, color: 'var(--muted)' }}>{r.cost_coins} монет</div>
                    </div>
                    <span style={{ background: 'var(--amber-light)', color: 'var(--amber)', borderRadius: 6, padding: '3px 10px', fontSize: 12 }}>⏳ Ждём</span>
                  </div>
                ))}
              </div>
            )}

            <h3 style={{ fontWeight: 600, margin: '20px 0 12px' }}>История наград</h3>
            {rewards.filter(r => r.status !== 'pending').map(r => (
              <div key={r.id} className="card" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 500 }}>{r.name}</div>
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>{r.cost_coins} монет</div>
                </div>
                <span style={{
                  borderRadius: 6, padding: '3px 10px', fontSize: 12,
                  background: r.status === 'approved' ? 'var(--green-light)' : 'var(--red-light)',
                  color: r.status === 'approved' ? 'var(--green)' : 'var(--red)',
                }}>
                  {r.status === 'approved' ? '✅ Одобрено' : '❌ Отклонено'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
