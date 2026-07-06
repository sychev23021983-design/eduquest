import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { useSettings } from '../context/SettingsContext.jsx'
import { api } from '../api.js'
import { MATERIAL_SUBJ, MATERIAL_SUBJ_ICON } from '../materialSubjects.js'
import '../game-theme.css'

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso.replace(' ', 'T') + 'Z').toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function SendAssignmentPanel({ token, onSent }) {
  const [open, setOpen] = useState(false)
  const [coins, setCoins] = useState(30)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)

  async function send() {
    setSending(true); setResult(null)
    try {
      const res = await api.createMaterialAssignment(token, { coins_reward: Number(coins) || 0, count: 3 })
      setResult({ ok: true, ...res })
      onSent?.()
    } catch (e) {
      setResult({ ok: false, error: e.message })
    }
    setSending(false)
  }

  if (!open) {
    return (
      <button className="gh-btn sm blue" style={{ marginBottom: 22, marginLeft: 12 }} onClick={() => { setOpen(true); setResult(null) }}>
        📨 Отправить на изучение
      </button>
    )
  }

  return (
    <div className="gh-card" style={{ marginBottom: 22, maxWidth: 440 }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>📨 Отправить материалы на изучение</div>
      <p style={{ fontSize: 13, color: 'var(--gh-muted)', marginBottom: 12 }}>
        Ребёнку в Telegram придёт сообщение с 3 темами и ссылкой. Темы выбираются автоматически —
        сначала те, что ещё ни разу не отправлялись, а когда все побывают в рассылке хотя бы раз,
        цикл начнётся заново с самых давно отправленных.
      </p>
      <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Награда (монет)</label>
      <input className="input" type="number" min={0} value={coins} onChange={e => setCoins(e.target.value)} style={{ width: 120, marginBottom: 14 }} />
      <div style={{ display: 'flex', gap: 10 }}>
        <button className="gh-btn sm" style={{ background: '#8a8a9a' }} onClick={() => setOpen(false)} disabled={sending}>Отмена</button>
        <button className="gh-btn sm blue" onClick={send} disabled={sending}>{sending ? 'Отправляю…' : 'Отправить →'}</button>
      </div>
      {result && result.ok && (
        <div style={{ marginTop: 14, fontSize: 13, color: result.telegram_ok ? 'var(--gh-green)' : '#f0a020' }}>
          {result.telegram_ok
            ? `✅ Отправлено! Темы: ${result.titles.join(', ')}`
            : `⚠️ Задание создано (темы: ${result.titles.join(', ')}), но Telegram не доставил сообщение: ${result.telegram_error || 'неизвестная ошибка'}. Проверь настройки Telegram в Настройках.`}
        </div>
      )}
      {result && !result.ok && (
        <div style={{ marginTop: 14, fontSize: 13, color: '#f87171' }}>❌ {result.error}</div>
      )}
    </div>
  )
}

function AssignmentHistory({ token, refreshKey }) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState(null)

  useEffect(() => { if (open) load() }, [open, refreshKey])

  async function load() {
    try { setList(await api.materialAssignments(token)) } catch { setList([]) }
  }

  return (
    <div className="gh-card" style={{ padding: 0, overflow: 'hidden', marginBottom: 22, maxWidth: 640 }}>
      <div onClick={() => setOpen(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', cursor: 'pointer' }}>
        <span style={{ fontWeight: 700, flex: 1 }}>📋 История отправленных материалов</span>
        <span style={{ transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--gh-muted)' }}>▾</span>
      </div>
      {open && (
        <div style={{ padding: '0 16px 16px' }}>
          {list === null && <div style={{ fontSize: 13, color: 'var(--gh-muted)' }}>Загрузка…</div>}
          {list && list.length === 0 && <div style={{ fontSize: 13, color: 'var(--gh-muted)' }}>Пока ничего не отправлялось.</div>}
          {list && list.map(a => (
            <div key={a.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--gh-border)', fontSize: 13 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ fontWeight: 600 }}>{formatDate(a.sent_at)}</span>
                <span>
                  {a.completed_at
                    ? <span style={{ color: '#4ade80' }}>✅ Изучено {formatDate(a.completed_at)}</span>
                    : <span style={{ color: 'var(--gh-muted)' }}>⏳ Ещё не изучено</span>}
                </span>
              </div>
              <div style={{ marginTop: 2 }}>{a.titles.join(', ')}</div>
              <div style={{ marginTop: 2, color: 'var(--gh-muted)' }}>
                🪙 {a.coins_reward} монет{!a.telegram_ok && <span style={{ color: '#f0a020' }}> · ⚠️ Telegram не доставлен{a.telegram_error ? `: ${a.telegram_error}` : ''}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function MaterialsPage() {
  const { token, role } = useAuth()
  const { settings } = useSettings()
  const nav = useNavigate()
  const [subjects, setSubjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [historyKey, setHistoryKey] = useState(0)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    const data = await api.materialSubjects(token)
    setSubjects(data)
    setLoading(false)
  }

  const pageStyle = settings?.bg_main ? {
    backgroundImage: `url(${settings.bg_main})`, backgroundSize: 'cover', backgroundPosition: 'center', backgroundAttachment: 'fixed',
  } : {}

  return (
    <div className="game-home" style={pageStyle}>
      <div className="gh-map-topbar">
        <button className="gh-back-btn" onClick={() => nav('/')}>‹</button>
        <div className="gh-map-title">
          <span className="gh-map-title-text">📚 ПОЗНАВАТЕЛЬНЫЕ МАТЕРИАЛЫ</span>
        </div>
      </div>

      <div className="gh-wrap">
        <p style={{ color: 'var(--gh-muted)', margin: '18px 0 22px', maxWidth: 560 }}>
          Интересные факты и объяснения на разные темы — без тестов и оценок. Просто читай и узнавай новое!
        </p>

        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <button className="gh-btn" style={{ marginBottom: 22 }} onClick={() => nav('/materials/slideshow')}>
            🎞️ Слайд-шоу картинок
          </button>
          {role === 'parent' && <SendAssignmentPanel token={token} onSent={() => setHistoryKey(k => k + 1)} />}
        </div>

        {role === 'parent' && <AssignmentHistory token={token} refreshKey={historyKey} />}

        {loading && <div className="gh-empty">🔍 Загружаю темы…</div>}

        {!loading && (
          <div className="gh-subjects-grid">
            {subjects.map(s => (
              <div key={s.key} className={`gh-subject-card ${s.key}`} onClick={() => nav(`/materials/${s.key}`)}>
                <div className="icon"><span style={{ fontSize: 56 }}>{MATERIAL_SUBJ_ICON[s.key]}</span></div>
                <div className="name">{MATERIAL_SUBJ[s.key] || s.label}</div>
                <div className="count">{s.count} {s.count === 1 ? 'материал' : 'материалов'}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

