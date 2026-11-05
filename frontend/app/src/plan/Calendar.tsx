// F18 calendar heat map: three months, each day coloured by what the API says for this site.
// Click a day to put the launch knob there; the arrows move the 90-day search to other months
// (a new /api/landing-windows request, cached).
import { classifyDays, type CalDay } from './calendarDays';
import { SEARCH_DAYS, utcMidnight, type PlanData, type PlanSettings } from './usePlan';
import { CloseIcon } from '../ui/Icons';

const DAY = 86400e3;
const WEEK = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

type Props = { settings: PlanSettings; data: PlanData; onSettings: (p: Partial<PlanSettings>) => void; onClose: () => void };

export function Calendar({ settings, data, onSettings, onClose }: Props) {
  const start = settings.searchStartMs, end = start + SEARCH_DAYS * DAY;
  const s = new Date(start);
  const months = [0, 1, 2, 3].map((k) => Date.UTC(s.getUTCFullYear(), s.getUTCMonth() + k, 1));
  const ready = data.status === 'ready';
  const today = utcMidnight(Date.now());
  const knobDay = utcMidnight(settings.notBeforeMs);

  const pick = (d: CalDay) => {
    if (d.ms >= start && d.ms < end) onSettings({ notBeforeMs: d.ms });
    else onSettings({ searchStartMs: d.ms, notBeforeMs: d.ms });
  };
  const shift = (days: number) => {
    const t = utcMidnight(start + days * DAY);
    onSettings({ searchStartMs: t, notBeforeMs: t });
  };

  return (
    <div className="la-cal" role="dialog" aria-label="Landing calendar">
      <div className="la-cal-nav">
        <button type="button" className="la-btn icon" aria-label="Earlier month" onClick={() => shift(-30)}>‹</button>
        <button type="button" className="la-btn icon" aria-label="Later month" onClick={() => shift(30)}>›</button>
        <span className="la-cap">{data.status === 'loading' ? 'Searching…' : `Search ${new Date(start).toISOString().slice(0, 10)} + ${SEARCH_DAYS} d`}</span>
        <span className="la-spacer" />
        <button type="button" className="la-btn icon" aria-label="Close calendar" onClick={onClose}><CloseIcon /></button>
      </div>
      <div className="la-cal-months">
        {months.slice(0, 3).map((m0, k) => {
          const m1 = months[k + 1];
          const days = classifyDays(m0, m1, ready ? data.landing.opportunities : [], ready && data.bands ? data.bands.sun : null, ready ? start : 0, ready ? end : 0);
          const lead = (new Date(m0).getUTCDay() + 6) % 7;
          return (
            <div key={m0} className="la-month">
              <h4>{new Date(m0).toLocaleDateString(undefined, { month: 'short', year: 'numeric', timeZone: 'UTC' })}</h4>
              <div className="la-days">
                {WEEK.map((w, i) => <span key={i}>{w}</span>)}
                {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} />)}
                {days.map((d) => {
                  const kind = ready ? d.kind : 'outside';
                  const date = new Date(d.ms).getUTCDate();
                  const what = kind === 'land' ? 'landing window' : kind === 'sun' ? `sunlit ${Math.round((d.sunFraction ?? 0) * 100)}% of the day` : kind === 'dark' ? 'dark' : kind === 'unknown' ? 'sunlight not loaded yet' : 'outside the search';
                  return (
                    <button key={d.ms} type="button" className={`la-day ${kind}${d.ms === knobDay ? ' knob' : ''}${d.ms === today ? ' today' : ''}`}
                      aria-label={`${new Date(d.ms).toISOString().slice(0, 10)}: ${what}`} title={what} onClick={() => pick(d)}>
                      {date}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      <div className="la-legend">
        <span><i style={{ background: 'var(--good)' }} />Landing window</span>
        <span><i style={{ background: 'rgba(242,184,75,.45)' }} />Sun up, no window</span>
        <span><i style={{ background: 'rgba(255,255,255,.06)', outline: '1px solid var(--line-2)' }} />Dark</span>
        <span>Days are UTC</span>
      </div>
    </div>
  );
}
