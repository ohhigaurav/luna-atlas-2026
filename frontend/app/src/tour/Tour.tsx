// Guided tour overlay: lights up one element of the real UI and shows a caption beside it. The
// app stays usable underneath (the dimming ignores the pointer). App.tsx runs each step's action.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { CHAPTERS, type Chapter, type TourStep } from './steps';

type Props = {
  chapter: Chapter;
  index: number;
  onStep: (index: number) => void;
  /** Starts the other chapter. */
  onChapter: (id: Chapter['id']) => void;
  onClose: () => void;
};

type Box = { x: number; y: number; w: number; h: number };
const PAD = 8;

/** Where the step's element is now; polled because panels open, load and animate after the action. */
function useTarget(step: TourStep): Box | null {
  const [box, setBox] = useState<Box | null>(null);
  const scrolled = useRef<Element | null>(null);
  useEffect(() => {
    scrolled.current = null;
    setBox(null);
    const measure = () => {
      const el = document.querySelector(step.target);
      if (!el) { setBox((b) => (b ? null : b)); return; }
      if (scrolled.current !== el) { scrolled.current = el; el.scrollIntoView?.({ block: 'nearest' }); }
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) { setBox(null); return; }
      setBox((b) => (b && Math.abs(b.x - r.left) < 1 && Math.abs(b.y - r.top) < 1 && Math.abs(b.w - r.width) < 1 && Math.abs(b.h - r.height) < 1
        ? b : { x: r.left, y: r.top, w: r.width, h: r.height }));
    };
    measure();
    const t = setInterval(measure, 250);
    window.addEventListener('resize', measure);
    return () => { clearInterval(t); window.removeEventListener('resize', measure); };
  }, [step.target, step.id]);
  return box;
}

export function Tour({ chapter, index, onStep, onChapter, onClose }: Props) {
  const step = chapter.steps[index];
  const box = useTarget(step);
  const card = useRef<HTMLDivElement>(null);
  const last = index === chapter.steps.length - 1;
  const other = CHAPTERS.find((c) => c.id !== chapter.id)!;

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.defaultPrevented || (e.target as HTMLElement | null)?.closest?.('input, select, textarea')) return;
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight' && !last) onStep(index + 1);
      else if (e.key === 'ArrowLeft' && index > 0) onStep(index - 1);
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [index, last, onStep, onClose]);
  useLayoutEffect(() => { card.current?.querySelector<HTMLButtonElement>('.tour-next')?.focus({ preventScroll: true }); }, [chapter.id, index]);

  // Caption beside the lit element: on the side with more room; centred at the bottom when the
  // element is big (a whole sheet), missing (still loading) or the screen is narrow.
  const vw = window.innerWidth, vh = window.innerHeight, W = Math.min(380, vw - 24);
  let pos: CSSProperties = { left: (vw - W) / 2, bottom: 24 };
  if (box && vw > 900 && box.w < vw * 0.6) {
    const right = box.x + box.w + PAD + 16, left = box.x - PAD - 16 - W;
    const top = Math.max(84, Math.min(vh - 300, box.y));
    if (right + W < vw - 12) pos = { left: right, top };
    else if (left > 12) pos = { left, top };
  }

  return (
    <div className="la-tour" aria-live="polite">
      {box
        ? <div className="tour-spot" style={{ left: box.x - PAD, top: box.y - PAD, width: box.w + 2 * PAD, height: box.h + 2 * PAD }} />
        : <div className="tour-dim" />}
      <div ref={card} className="tour-card" role="dialog" aria-label={`Tour: ${chapter.title}`} style={{ ...pos, width: W }}>
        <div className="tour-head">
          <span className="la-cap">{chapter.title} · {index + 1} of {chapter.steps.length}</span>
          <button type="button" className="tour-skip" onClick={onClose}>Skip tour</button>
        </div>
        <h2>{step.title}</h2>
        <p>{step.body}</p>
        {step.link && <a href={step.link.href} target="_blank" rel="noreferrer">{step.link.label}</a>}
        {!box && <p className="tour-wait">Waiting for this part of the app to load…</p>}
        <div className="tour-dots" aria-hidden="true">{chapter.steps.map((s, i) => <i key={s.id} className={i === index ? 'on' : undefined} />)}</div>
        <div className="tour-nav">
          {index > 0 && <button type="button" className="la-btn" onClick={() => onStep(index - 1)}>Back</button>}
          <span className="la-spacer" />
          {last ? (
            <>
              <button type="button" className="la-btn" onClick={() => onChapter(other.id)}>{other.title} →</button>
              <button type="button" className="la-btn primary tour-next" onClick={onClose}>Done</button>
            </>
          ) : (
            <button type="button" className="la-btn primary tour-next" onClick={() => onStep(index + 1)}>Next</button>
          )}
        </div>
      </div>
    </div>
  );
}
