// The date comes first: one bar at the top, the moment every answer on screen is for. Step a day
// back or forward, type a date, play time forward, or return to now. The thin track under it
// scrubs through the loaded days.
import { useEffect, useRef, useState } from 'react';
import { PlayIcon } from './Icons';

type Props = {
  ms: number;
  live: boolean;
  following: boolean;
  playing: boolean;
  speedLabel: string;
  range: [number, number];
  onSet: (ms: number) => void;
  onPlay: () => void;
  onSpeed: () => void;
  onNow: () => void;
};

const DAY = 86400e3;
const dayName = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const hm = (ms: number) => new Date(ms).toISOString().slice(11, 16);

export function DateBar({ ms, live, following, playing, speedLabel, range, onSet, onPlay, onSpeed, onNow }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const k = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    window.addEventListener('mousedown', k);
    return () => window.removeEventListener('mousedown', k);
  }, [open]);
  const d = new Date(ms);
  const dateVal = d.toISOString().slice(0, 10), timeVal = hm(ms);
  const set = (date: string, time: string) => { const t = Date.parse(`${date}T${time}:00Z`); if (Number.isFinite(t)) onSet(t); };
  const year = d.getUTCFullYear();

  return (
    <div className="la-datebar" ref={box}>
      <div className="db-row">
        <button type="button" className="db-step" aria-label="One day earlier" onClick={() => onSet(ms - DAY)}>‹</button>
        <button type="button" className="db-date" aria-expanded={open} onClick={() => setOpen((o) => !o)} title="Change the date">
          <b>{dayName(ms)}</b>
          <span>{timeVal} UTC{following ? ', now' : ''}</span>
        </button>
        <button type="button" className="db-step" aria-label="One day later" onClick={() => onSet(ms + DAY)}>›</button>
        <span className="db-sep" />
        <button type="button" className="db-play" aria-label={playing ? 'Pause' : 'Play time forward'} onClick={onPlay}><PlayIcon playing={playing} size={14} /></button>
        <button type="button" className="db-speed" aria-label="Playback speed" onClick={onSpeed}>{speedLabel}</button>
        {live && (
          <button type="button" className={`db-now${following ? ' on' : ''}`} aria-pressed={following} onClick={onNow}>
            <i className={`la-live${following ? '' : ' off'}`} aria-hidden="true" />Now
          </button>
        )}
      </div>
      <input className="db-track" type="range" aria-label="Scrub time" min={range[0]} max={range[1]} step={30 * 60e3}
        value={Math.min(range[1], Math.max(range[0], ms))} onChange={(e) => onSet(Number(e.target.value))} />
      {open && (
        <div className="db-pop" role="dialog" aria-label="Choose a date">
          <label><span>Date (UTC)</span><input type="date" value={dateVal} onChange={(e) => set(e.target.value, timeVal)} /></label>
          <label><span>Time (UTC)</span><input type="time" value={timeVal} step={1800} onChange={(e) => set(dateVal, e.target.value)} /></label>
          <div className="db-quick">
            {live && <button type="button" onClick={() => { onNow(); setOpen(false); }}>Today</button>}
            <button type="button" onClick={() => onSet(ms + 7 * DAY)}>+1 week</button>
            <button type="button" onClick={() => onSet(ms + Math.round(29.53 * 24) * 3600e3)}>+1 lunar month</button>
            <button type="button" onClick={() => set(`${year + 1}-01-01`, '00:00')}>1 Jan {year + 1}</button>
          </div>
          <p>Every answer on screen is for this moment. Local time: {d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}.</p>
        </div>
      )}
    </div>
  );
}
