import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api } from '../api.js'
import dayjs from 'dayjs'

const SUBJ = { math: 'Математика', russian: 'Русский язык', science: 'Окружающий мир', history: 'История' }
const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }

export default function ParentDashboard() {
  const { token, logout } = useAuth()
  const nav = useNavigate()
  const [tab,     setTab]     = useState('stats')
  const [stats,   setStats]   = useState(null)
  const [lessons, setLessons] = useState([])
  const [rewards, setRewards] = useState([])
  const [balance, setBalance] = useState({})

  useEffect(() => { load() }, [])

  async function load() {
    const [st, ls, rw, bl] = await Promise.all([
      api.stats(token), api.lessons(token), api.rewards(token), api.balance(token)
    ])
    setStats(st); setLessons(ls); setRewards(rw); setBalance(bl)
  }

  async function approve(id) {
    await api.approveReward(token, id)
    load()
  }
  async function reject(id) {
    await api.rejectReward(token, id)
    load()
  }
  async function deleteLesson(id) {
    if (!confirm('Удалить урок?')) return
    await api.deleteLesson(token, id)
    load()
  }

  const pending = rewards.filter(r => r.status === 'pending')

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      <div style={{ background: '#1a1a2e', padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#fff', fontWeight: 700, fontSize: 18 }}>👨‍💼 Кабинет родителя</span>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ background: '#faeeda', color: '#7a4a00', borderRadius: 20, padding: '4px 12px', fontSize: 13, fontWeight: 600 }}>
            🪙 {balance.balance || 0} монет
          </span>
          <button onClick={logout} style={{ background: 'none', border: 'none', color: '#aaa', fontSize: 13 }}>Выйти</button>
        </div>
      </div>

      <div style={{ background: '#fff', borderBottom: '1px solid var(--border)', display: 'flex', gap: 0, overflowX: 'auto' }}>
        {[['stats','📊 Аналитика'],['rewards','🎁 Награды' + (pending.length ? ` (${pending.length})` : '')],['lessons','📚 Уроки']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: '12px 20px', border: 'none', background: 'none', fontWeight: tab === k ? 600 : 400,
            color: tab === k ? 'var(--blue)' : 'var(--muted)', whiteSpace: 'nowrap',
            borderBottom: tab === k ? '2px solid var(--blue)' : '2px solid transparent', fontSize: 14
          }}>{l}</button>
        ))}
      </div>

      <div className="page-wide">

        {/* ANALYTICS */}
        {tab === 'stats' && stats && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 24 }}>
              {[
                ['Уроков пройдено', stats.total_lessons, '📚'],
                ['Баланс монет', balance.balance || 0, '🪙'],
                ['Заработано всего', balance.earned || 0, '💰'],
                ['Серия дней', (stats.streak_days || 0) + ' дн.', '🔥'],
                ['Точность', (stats.avg_score || 0) + '%', '🎯'],
              ].map(([l, v, i]) => (
                <div key={l} className="card" style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 24 }}>{i}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{v}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>{l}</div>
                </div>
              ))}
            </div>

            <h3 style={{ fontWeight: 600, marginBottom: 12 }}>По предметам</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12, marginBottom: 24 }}>
              {stats.by_subject.map(s => (
                <div key={s.subject} className="card">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    <span style={{ fontSize: 20 }}>{SUBJ_ICON[s.subject]}</span>
                    <span style={{ fontWeight: 600 }}>{SUBJ[s.subject]}</span>
                  </div>
                  <div style={{ height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden', marginBottom: 6 }}>
                    <div style={{ height: '100%', background: 'var(--blue)', width: `${Math.round(s.avg * 100)}%`, borderRadius: 3 }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: 'var(--muted)' }}>
                    <span>{s.cnt} урок(ов)</span>
                    <span>{Math.round(s.avg * 100)}% точность</span>
                  </div>
                </div>
              ))}
            </div>

            {stats.week_activity.length > 0 && (
              <>
                <h3 style={{ fontWeight: 600, marginBottom: 12 }}>Активность за 7 дней</h3>
                <div className="card" style={{ marginBottom: 24 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', height: 100 }}>
                    {stats.week_activity.map(d => (
                      <div key={d.day} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                        <div style={{ width: '100%', background: 'var(--border)', borderRadius: 4, overflow: 'hidden', height: 70, display: 'flex', alignItems: 'flex-end' }}>
                          <div style={{ width: '100%', background: 'var(--blue)', height: `${Math.min((d.cnt / 3) * 100, 100)}%`, borderRadius: '4px 4px 0 0' }} />
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--muted)' }}>{dayjs(d.day).format('dd')}</div>
                        <div style={{ fontSize: 11, fontWeight: 600 }}>{d.cnt}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}

            {stats.weak_topics.length > 0 && (
              <>
                <h3 style={{ fontWeight: 600, marginBottom: 12, color: 'var(--red)' }}>⚠️ Слабые места</h3>
                {stats.weak_topics.map(t => (
                  <div key={t.topic} className="card" style={{ marginBottom: 8, borderLeft: '3px solid var(--amber)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <span className={`badge badge-${t.subject}`}>{SUBJ[t.subject]}</span>
                        <div style={{ fontWeight: 500, marginTop: 4 }}>{t.topic}</div>
                        <div style={{ fontSize: 13, color: 'var(--muted)' }}>{t.attempts} попытки · {Math.round(t.avg * 100)}% точность</div>
                      </div>
                      <span style={{ fontSize: 24 }}>📉</span>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {/* REWARDS */}
        {tab === 'rewards' && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
              <div className="card" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>Текущий баланс</div>
                <div style={{ fontSize: 26, fontWeight: 700 }}>{balance.balance || 0} 🪙</div>
              </div>
              <div className="card" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>Потрачено всего</div>
                <div style={{ fontSize: 26, fontWeight: 700 }}>{balance.spent || 0} 🪙</div>
              </div>
            </div>

            {pending.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <h3 style={{ fontWeight: 600, marginBottom: 12, color: 'var(--amber)' }}>⏳ Ожидают одобрения</h3>
                {pending.map(r => (
                  <div key={r.id} className="card" style={{ marginBottom: 10, borderLeft: '3px solid var(--amber)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 16 }}>{r.name}</div>
                        <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                          {r.cost_coins} монет · {dayjs(r.requested_at).format('DD.MM HH:mm')}
                        </div>
                      </div>
                      <button className="btn btn-success btn-sm" onClick={() => approve(r.id)}>✅ Одобрить</button>
                      <button className="btn btn-danger btn-sm" onClick={() => reject(r.id)}>❌</button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <h3 style={{ fontWeight: 600, marginBottom: 12 }}>История</h3>
            {rewards.filter(r => r.status !== 'pending').map(r => (
              <div key={r.id} className="card" style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 500 }}>{r.name}</div>
                  <div style={{ fontSize: 13, color: 'var(--muted)' }}>
                    {r.cost_coins} монет · {dayjs(r.requested_at).format('DD.MM HH:mm')}
                  </div>
                </div>
                <span style={{ padding: '3px 10px', borderRadius: 6, fontSize: 12,
                  background: r.status === 'approved' ? 'var(--green-light)' : 'var(--red-light)',
                  color: r.status === 'approved' ? 'var(--green)' : 'var(--red)' }}>
                  {r.status === 'approved' ? '✅ Одобрено' : '❌ Отклонено'}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* LESSONS */}
        {tab === 'lessons' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ fontWeight: 600 }}>Все уроки ({lessons.length})</h3>
              <button className="btn btn-primary" onClick={() => nav('/parent/lesson/new')}>+ Добавить урок</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {lessons.map(l => (
                <div key={l.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: 22 }}>{SUBJ_ICON[l.subject]}</span>
                  <div style={{ flex: 1 }}>
                    <span className={`badge badge-${l.subject}`}>{SUBJ[l.subject]}</span>
                    <div style={{ fontWeight: 500, marginTop: 2 }}>{l.topic}</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)', display: 'flex', gap: 12, marginTop: 2 }}>
                      <span>{l.audio_file ? '🎧 Аудио' : '— Нет аудио'}</span>
                      <span>{l.infographic ? '🖼️ Инфографика' : '— Нет картинки'}</span>
                      <span>🪙 {l.coins_lesson}+{l.coins_boss}</span>
                    </div>
                  </div>
                  <button className="btn btn-sm" onClick={() => nav(`/parent/lesson/${l.id}/edit`)}>✏️ Изменить</button>
                  <button className="btn btn-sm" style={{ color: 'var(--red)', borderColor: 'var(--red)' }}
                          onClick={() => deleteLesson(l.id)}>🗑️</button>
                </div>
              ))}
              {lessons.length === 0 && (
                <div className="card" style={{ textAlign: 'center', padding: 48, color: 'var(--muted)' }}>
                  <div style={{ fontSize: 40, marginBottom: 12 }}>📚</div>
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>Уроков пока нет</div>
                  <button className="btn btn-primary" onClick={() => nav('/parent/lesson/new')}>Создать первый урок</button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
