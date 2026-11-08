// "When is the best date?" (handoff A, the team 8 Nov: "the best possible date, whether it is 30, 90,
// 200 or 365 days"). Three answers from /api/landing-windows over the chosen look-ahead, counted
// from the date bar: the soonest window, the one with the most sunlight after touchdown, and the
// one with the most Earth in view during the mission. Shows the trade-off; never one magic date.
import { useEffect, useState } from 'react';
import type { LandingOpportunity, LandingResult } from '../api/plan';
import { ApiError } from '../api/plan';
import { staticIndex } from '../data/staticMode';
import { spanText } from '../state/siteState';
import { landingRequest, utcMidnight } from './usePlan';

const AHEAD = [30, 90, 180, 365];
const day = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const d1 = (h: number) => `${(h / 24).toFixed(1)} d`;

type Props = {
  siteId: string;
  cursorMs: number;
  missionDays: number;
  maxSunDeg: number | null;
  onJump: (ms: number) => void;
  onStand: (ms: number, note: string) => void;
};

export function BestDate({ siteId, cursorMs, missionDays, maxSunDeg, onJump, onStand }: Props) {
  const [ahead, setAhead] = useState(90);
  const start = utcMidnight(cursorMs);
  const [st, setSt] = useState<{ key: string; r?: LandingResult; err?: string; t0: number }>({ key: '', t0: 0 });
  const [, tick] = useState(0);
  const key = JSON.stringify([siteId, start, missionDays, maxSunDeg, ahead]);
  const fixed = !!staticIndex();

  useEffect(() => {
    let off = false;
    setSt({ key, t0: Date.now() });
    landingRequest(siteId, start, missionDays, maxSunDeg, ahead).then(
      (r) => { if (!off) setSt((s) => ({ ...s, key, r })); },
      (e: unknown) => { if (!off) setSt((s) => ({ ...s, key, err: e instanceof ApiError ? e.message : String(e) })); },
    );
    return () => { off = true; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const loading = st.key !== key || (!st.r && !st.err);
  useEffect(() => {
    if (!loading) return;
    const t = setInterval(() => tick((k) => k + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  const r = st.key === key ? st.r : undefined;
  const at = (o: LandingOpportunity) => Date.parse(o.best_touchdown_utc);
  const line = (label: string, o: LandingOpportunity & { rank?: number }, detail: string) => (
    <li>
      <span className="bd-l">{label}</span>
      <span className="bd-d"><b>{day(at(o))}</b> · {detail}</span>
      <button type="button" className="c-go" onClick={() => onJump(at(o))} aria-label={`Go to ${day(at(o))}`}>Go to</button>
    </li>
  );
  const opens = (o: LandingOpportunity) => Date.parse(o.touchdown_from_utc);
  const sun = (o: LandingOpportunity) => `${o.daylight_is_lower_bound ? '≥ ' : ''}${d1(o.daylight_after_best_h)} of sun`;
  const earth = (o: LandingOpportunity) => `Earth ${o.earth_in_view_during_mission_pct.toFixed(0)}% of the mission`;

  // An older backend or bake has no soonest/best: fall back to the first listed window, never to "none".
  const first = r ? (r.soonest !== undefined ? r.soonest : r.opportunities[0] ?? null) : null;
  let body;
  if (loading) body = <p className="bd-wait">Searching the next {ahead} days… {Math.round((Date.now() - st.t0) / 1000)} s{ahead > 90 ? ' (a year takes up to a minute the first time)' : ''}</p>;
  else if (st.err) body = <p className="bd-wait">{st.err}</p>;
  else if (r && !first) body = <p className="bd-wait">No landing window in the {ahead} days from {day(start)} for a {missionDays}-day mission.</p>;
  else if (r && first) {
    const s = first, b = r.best ?? null, e = r.best_earth ?? null;
    const same = (x: LandingOpportunity | null, y: LandingOpportunity | null) => !!x && !!y && x.best_touchdown_utc === y.best_touchdown_utc;
    body = (
      <>
        <ul className="bd-list" title={r.best_rule}>
          {line('Soonest (best moment in the first window)', s, `${opens(s) > cursorMs ? `window opens in ${spanText(opens(s) - cursorMs)}` : 'window open now'}, ${sun(s)}`)}
          {b && !same(b, s) && line('Most sunlight', b, `${sun(b)}, ${earth(b)}`)}
          {e && !same(e, s) && !same(e, b) && line('Most Earth contact', e, `${earth(e)}, ${sun(e)}`)}
        </ul>
        {same(b, s) && same(e, s) && <p className="bd-note">The soonest window is also the best in the next {ahead} days, for sunlight and for Earth.</p>}
        {same(b, s) && !same(e, s) && <p className="bd-note">The soonest window also has the most sunlight.</p>}
        {b && (
          <button type="button" className="la-btn" onClick={() => onStand(at(b), `Starting at the sunniest landing date in the next ${ahead} days, ${day(at(b))}.`)}>
            Play the mission from the sunniest date
          </button>
        )}
      </>
    );
  }

  return (
    <section className="sc-best" aria-label="Best landing date">
      <div className="bd-head">
        <span>Best date in the next</span>
        <div className="bd-seg" role="group" aria-label="Look ahead">
          {AHEAD.map((d) => (
            <button key={d} type="button" className={d === ahead ? 'on' : undefined} aria-pressed={d === ahead}
              disabled={fixed && d !== 90} title={fixed && d !== 90 ? 'needs the live backend' : undefined} onClick={() => setAhead(d)}>{d} d</button>
          ))}
        </div>
      </div>
      {body}
    </section>
  );
}
