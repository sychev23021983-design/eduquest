const SUBJ_ICON = { math: '🔢', russian: '📝', science: '🌿', history: '🏛️' }

export default function SubjectIcon({ subj, icons, size = 28 }) {
  const custom = icons?.[subj]
  if (custom) return <img src={custom} alt="" style={{ width: size, height: size, objectFit: 'contain' }} />
  return <span style={{ fontSize: size }}>{SUBJ_ICON[subj]}</span>
}

export { SUBJ_ICON }
