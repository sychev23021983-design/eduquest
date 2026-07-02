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
  config:         ()                => req('GET', '/config'),
  lessons:        (token, subject, topicId) => req('GET', `/lessons?${subject ? `subject=${subject}&` : ''}${topicId ? `topic_id=${topicId}` : ''}`, null, token),
  lesson:         (token, id)       => req('GET', `/lessons/${id}`, null, token),
  curriculum:     (token, grade, subject) => req('GET', `/curriculum?grade=${grade}&subject=${subject}`, null, token),
  createSection:  (token, data)     => req('POST', '/sections', data, token),
  updateSection:  (token, id, data) => req('PUT', `/sections/${id}`, data, token),
  deleteSection:  (token, id)       => req('DELETE', `/sections/${id}`, null, token),
  createTopic:    (token, data)     => req('POST', '/topics', data, token),
  updateTopic:    (token, id, data) => req('PUT', `/topics/${id}`, data, token),
  deleteTopic:    (token, id)       => req('DELETE', `/topics/${id}`, null, token),
  topic:          (token, id)       => req('GET', `/topics/${id}`, null, token),
  importCurriculum: (token, data)   => req('POST', '/curriculum/import', data, token),
  section:        (token, id)       => req('GET', `/sections/${id}`, null, token),
  completeIntro:  (token, id)       => req('POST', `/sections/${id}/intro-done`, {}, token),
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
