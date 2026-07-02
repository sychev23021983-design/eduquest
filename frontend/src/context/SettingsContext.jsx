import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import { api } from '../api.js'

const SettingsContext = createContext(null)

const GOOGLE_FONT_SLUGS = {
  'Nunito':     'Nunito:wght@400;600;700;800;900',
  'Rubik':      'Rubik:wght@400;600;700;800',
  'Montserrat': 'Montserrat:wght@400;600;700;800',
  'PT Sans':    'PT+Sans:wght@400;700',
  'Comfortaa':  'Comfortaa:wght@400;600;700',
  'Ubuntu':     'Ubuntu:wght@400;500;700',
}

function ensureGoogleFont(family) {
  if (!family || !GOOGLE_FONT_SLUGS[family]) return
  const id = `gf-${family.replace(/\s+/g, '-')}`
  if (document.getElementById(id)) return
  const link = document.createElement('link')
  link.id = id
  link.rel = 'stylesheet'
  link.href = `https://fonts.googleapis.com/css2?family=${GOOGLE_FONT_SLUGS[family]}&display=swap`
  document.head.appendChild(link)
}

function applyFavicon(url) {
  if (!url) return
  let link = document.querySelector('link[rel="icon"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.href = url
}

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(null)

  const refresh = useCallback(async () => {
    const s = await api.settings()
    setSettings(s)
    ensureGoogleFont(s.font_heading)
    ensureGoogleFont(s.font_body)
    applyFavicon(s.favicon_url)
    document.documentElement.style.setProperty('--gh-blue-user', s.color_accent || '')
    document.documentElement.style.setProperty('--gh-green-user', s.color_accent2 || '')
    document.documentElement.style.setProperty('--font-heading-user', s.font_heading && s.font_heading !== 'Baloo 2' ? `'${s.font_heading}'` : '')
    document.documentElement.style.setProperty('--font-body-user', s.font_body && s.font_body !== 'Nunito' ? `'${s.font_body}'` : '')
    return s
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <SettingsContext.Provider value={{ settings, refresh }}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsProvider')
  return ctx
}

export { GOOGLE_FONT_SLUGS }
