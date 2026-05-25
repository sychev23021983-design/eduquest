const BASE = '/api'

async function req(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function upload(path, formData, token) {
  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, { method: 'POST', headers, body: formData })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export const api = {
  login:          (data)            => req('POST', '/login', data),
  lessons:        (token, subject)  => req('GET', `/lessons${subject ? `?subject=${subject}` : ''}`, null, token),
  lesson:         (token, id)       => req('GET', `/lessons/${id}`, null, token),
  createLesson:   (token, data)     => req('POST', '/lessons', data, token),
  updateLesson:   (token, id, data) => req('PUT', `/lessons/${id}`, data, token),
  deleteLesson:   (token, id)       => req('DELETE', `/lessons/${id}`, null, token),
  uploadAudio:    (token, id, form) => upload(`/lessons/${id}/upload-audio`, form, token),
  uploadImage:    (token, id, form) => upload(`/lessons/${id}/upload-image`, form, token),
  startLesson:    (token, id)       => req('POST', '/progress/start', { lesson_id: id }, token),
  finishLesson:   (token, data)     => req('POST', '/progress/finish', data, token),
  progress:       (token)           => req('GET', '/progress', null, token),
  stats:          (token)           => req('GET', '/stats', null, token),
  balance:        (token)           => req('GET', '/coins/balance', null, token),
  requestReward:  (token, data)     => req('POST', '/rewards/request', data, token),
  rewards:        (token)           => req('GET', '/rewards', null, token),
  approveReward:  (token, id)       => req('POST', `/rewards/${id}/approve`, {}, token),
  rejectReward:   (token, id)       => req('POST', `/rewards/${id}/reject`, {}, token),
}
