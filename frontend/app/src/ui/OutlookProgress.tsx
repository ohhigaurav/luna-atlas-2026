// "Finding landing windows: 12 of 25 sites, about 2 min left" while the pins are being checked,
// so a visitor sees that work is going on and roughly how long it takes. The time left is an
// estimate from how long the checked sites took (state/outlook.ts etaMs) and counts down.
import { useEffect, useState } from 'react';
import { etaText } from '../state/outlook';

type Props = { checked: number; total: number; etaMs: number | null; at: number };

export function OutlookProgress({ checked, total, etaMs, at }: Props) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((k) => k + 1), 1000);
    return () => clearInterval(t);
  }, []);
  if (!total || checked >= total) return null;
  const left = etaMs === null ? null : Math.max(0, etaMs - (performance.now() - at));
  return (
    <div className="la-progress" role="status" aria-live="polite">
      <span>Finding landing windows: {checked} of {total} sites{left !== null ? `, ${etaText(left)}` : ''}</span>
      <i aria-hidden="true"><b style={{ width: `${(checked / total) * 100}%` }} /></i>
    </div>
  );
}
