import { useEffect, useState } from 'react'
import { api } from '../api.js'

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Date(iso.replace(' ', 'T') + 'Z').toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

export function SendAssignmentPanel({ token, onSent }) {
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
      <button className="btn btn-primary" onClick={() => { setOpen(true); setResult(null) }}>
        📨 Отправить на изучение
      </button>
    )
  }

  return (
    <div className="card" style={{ marginBottom: 20, maxWidth: 460 }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>📨 Отправить материалы на изучение</div>
      <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12 }}>
        Ребёнку в Telegram придёт сообщение с 3 темами и ссылкой. Темы выбираются автоматически —
        сначала те, что ещё ни разу не отправлялись, а когда все побывают в рассылке хотя бы раз,
        цикл начнётся заново с самых давно отправленных.
      </p>
      <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Награда (монет)</label>
      <input className="input" type="number" min={0} value={coins} onChange={e => setCoins(e.target.value)} style={{ width: 120, marginBottom: 14 }} />
      <div style={{ display: 'flex', gap: 10 }}>
        <button className="btn" onClick={() => setOpen(false)} disabled={sending}>Отмена</button>
        <button className="btn btn-primary" onClick={send} disabled={sending}>{sending ? 'Отправляю…' : 'Отправить →'}</button>
      </div>
      {result && result.ok && (
        <div style={{ marginTop: 14, fontSize: 13, color: result.telegram_ok ? 'var(--green)' : 'var(--amber)' }}>
          {result.telegram_ok
            ? `✅ Отправлено! Темы: ${result.titles.join(', ')}`
            : `⚠️ Задание создано (темы: ${result.titles.join(', ')}), но Telegram не доставил сообщение: ${result.telegram_error || 'неизвестная ошибка'}. Проверь настройки Telegram в Настройках.`}
        </div>
      )}
      {result && !result.ok && (
        <div style={{ marginTop: 14, fontSize: 13, color: 'var(--red)' }}>❌ {result.error}</div>
      )}
    </div>
  )
}

export function AssignmentHistory({ token, refreshKey }) {
  const [open, setOpen] = useState(false)
  const [list, setList] = useState(null)

  useEffect(() => { if (open) load() }, [open, refreshKey])

  async function load() {
    try { setList(await api.materialAssignments(token)) } catch { setList([]) }
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 20, maxWidth: 640 }}>
      <div onClick={() => setOpen(v => !v)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', cursor: 'pointer' }}>
        <span style={{ fontWeight: 700, flex: 1 }}>📋 История отправленных материалов</span>
        <span style={{ transition: 'transform .15s', transform: open ? 'rotate(180deg)' : 'none', fontSize: 14, color: 'var(--muted)' }}>▾</span>
      </div>
      {open && (
        <div style={{ padding: '0 16px 16px' }}>
          {list === null && <div style={{ fontSize: 13, color: 'var(--muted)' }}>Загрузка…</div>}
          {list && list.length === 0 && <div style={{ fontSize: 13, color: 'var(--muted)' }}>Пока ничего не отправлялось.</div>}
          {list && list.map(a => (
            <div key={a.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)', fontSize: 13 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ fontWeight: 600 }}>{formatDate(a.sent_at)}</span>
                <span>
                  {a.completed_at
                    ? <span style={{ color: 'var(--green)' }}>✅ Изучено {formatDate(a.completed_at)}</span>
                    : <span style={{ color: 'var(--muted)' }}>⏳ Ещё не изучено</span>}
                </span>
              </div>
              <div style={{ marginTop: 2 }}>{a.titles.join(', ')}</div>
              <div style={{ marginTop: 2, color: 'var(--muted)' }}>
                🪙 {a.coins_reward} монет{!a.telegram_ok && <span style={{ color: 'var(--amber)' }}> · ⚠️ Telegram не доставлен{a.telegram_error ? `: ${a.telegram_error}` : ''}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
