const BASE = '/api'

// Если токен просрочен/невалиден (или его нет), бэкенд отвечает 401 с detail
// "Invalid token". Раньше это всплывало на экране как сырая техническая ошибка
// (особенно на устройствах, где ребёнок открывал ссылку из Telegram впервые
// или после истечения 30-дневного токена). Теперь при 401 сразу стираем
// локальный токен и уводим на /login, чтобы человек просто заново вошёл по паролю.
function handleUnauthorized() {
  try {
    localStorage.removeItem('eq_token')
    localStorage.removeItem('eq_role')
  } catch {}
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    const back = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.href = `/login?next=${back}`
  }
}

async function req(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
  })
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized()
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

async function upload(path, formData, token) {
  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, { method: 'POST', headers, body: formData })
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized()
    throw new Error(`HTTP ${res.status}`)
  }
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
  settings:       ()                => req('GET', '/settings'),
  updateSettings: (token, data)     => req('PUT', '/settings', data, token),
  resetSettings:  (token)           => req('POST', '/settings/reset', {}, token),
  uploadSettingAsset: (token, slot, form) => upload(`/settings/upload?slot=${slot}`, form, token),
  coinPenalty:    (token, data)      => req('POST', '/coins/penalty', data, token),
  logMistake:     (token, data)      => req('POST', '/mistakes', data, token),
  mistakes:       (token)            => req('GET', '/mistakes', null, token),
  createLesson:   (token, data)     => req('POST', '/lessons', data, token),
  updateLesson:   (token, id, data) => req('PUT', `/lessons/${id}`, data, token),
  deleteLesson:   (token, id)       => req('DELETE', `/lessons/${id}`, null, token),
  uploadAudio:    (token, id, form) => upload(`/lessons/${id}/upload-audio`, form, token),
  uploadImage:    (token, id, form) => upload(`/lessons/${id}/upload-image`, form, token),
  clearInfographic: (token, id)     => req('DELETE', `/lessons/${id}/infographic`, null, token),
  startLesson:    (token, id)       => req('POST', '/progress/start', { lesson_id: id }, token),
  finishLesson:   (token, data)     => req('POST', '/progress/finish', data, token),
  progress:       (token)           => req('GET', '/progress', null, token),
  stats:          (token)           => req('GET', '/stats', null, token),
  balance:        (token)           => req('GET', '/coins/balance', null, token),
  requestReward:  (token, data)     => req('POST', '/rewards/request', data, token),
  rewards:        (token)           => req('GET', '/rewards', null, token),
  approveReward:  (token, id)       => req('POST', `/rewards/${id}/approve`, {}, token),
  rejectReward:   (token, id)       => req('POST', `/rewards/${id}/reject`, {}, token),
  materialSubjects: (token)         => req('GET', '/materials/subjects', null, token),
  articles:       (token, subject)  => req('GET', `/articles${subject ? `?subject=${subject}` : ''}`, null, token),
  article:        (token, id)       => req('GET', `/articles/${id}`, null, token),
  createArticle:  (token, data)     => req('POST', '/articles', data, token),
  updateArticle:  (token, id, data) => req('PUT', `/articles/${id}`, data, token),
  deleteArticle:  (token, id)       => req('DELETE', `/articles/${id}`, null, token),
  deletedArticles: (token)          => req('GET', `/articles/deleted/list`, null, token),
  restoreArticle: (token, id)       => req('POST', `/articles/${id}/restore`, null, token),
  purgeArticle:   (token, id)       => req('DELETE', `/articles/${id}/purge`, null, token),
  markArticleRead: (token, id)      => req('POST', `/articles/${id}/read`, {}, token),
  createMaterialAssignment: (token, data) => req('POST', '/materials/assignments', data, token),
  materialAssignments:      (token)       => req('GET', '/materials/assignments', null, token),
  materialAssignment:       (token, id)   => req('GET', `/materials/assignments/${id}`, null, token),
  completeMaterialAssignment: (token, id) => req('POST', `/materials/assignments/${id}/complete`, {}, token),
  telegramConfig:       (token)       => req('GET', '/integrations/telegram', null, token),
  updateTelegramConfig: (token, data) => req('PUT', '/integrations/telegram', data, token),
  testTelegram:         (token)       => req('POST', '/integrations/telegram/test', {}, token),
}
