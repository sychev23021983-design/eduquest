export function Block({ b, settings }) {
  switch (b.type) {
    case 'heading':
      return <h2 className="art-h">{b.text}</h2>
    case 'subheading':
      return <h3 className="art-h3">{b.text}</h3>
    case 'paragraph':
      return <p className="art-p">{b.text}</p>
    case 'callout':
      return <div className="art-callout">{b.text}</div>
    case 'flow':
      return <div className="art-flow">{b.text}</div>
    case 'list':
      return <ul className="art-list">{b.items.map((it, i) => <li key={i}>{it}</li>)}</ul>
    case 'checklist':
      return (
        <ul className="art-checklist">
          {b.items.map((it, i) => <li key={i}><span className="ck">✅</span>{it}</li>)}
        </ul>
      )
    case 'experiment':
      return (
        <div className="art-experiment">
          <div className="art-experiment-title">🧪 {b.title}</div>
          {b.materials?.length > 0 && (
            <>
              <div className="art-experiment-label">Тебе понадобится:</div>
              <ul className="art-list">{b.materials.map((m, i) => <li key={i}>{m}</li>)}</ul>
            </>
          )}
          {b.steps?.length > 0 && (
            <>
              <div className="art-experiment-label">Что делать:</div>
              <ol className="art-steps">{b.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
            </>
          )}
          {b.result && (
            <div className="art-experiment-result"><b>Что произойдёт?</b> {b.result}</div>
          )}
        </div>
      )
    case 'question':
      return <div className="art-question">💭 <b>Подумай:</b> {b.text}</div>
    case 'image': {
      const src = b.url || settings?.[b.slot]
      if (!src) return (
        <div className="art-image-placeholder">🖼️ Картинка «{b.caption || b.slot}» скоро появится</div>
      )
      return (
        <figure className="art-figure">
          <img src={src} alt={b.caption || ''} />
          {b.caption && <figcaption>{b.caption}</figcaption>}
        </figure>
      )
    }
    default:
      return null
  }
}

// Группирует блоки в слайды: каждый heading начинает новый слайд,
// всё до следующего heading относится к текущему слайду.
export function groupSlides(blocks) {
  const slides = []
  let cur = null
  for (const b of blocks) {
    if (b.type === 'heading') {
      cur = { blocks: [b] }
      slides.push(cur)
    } else {
      if (!cur) { cur = { blocks: [] }; slides.push(cur) }
      cur.blocks.push(b)
    }
  }
  return slides.length > 0 ? slides : [{ blocks: [] }]
}
