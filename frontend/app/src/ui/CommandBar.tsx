// Ctrl/⌘ K (PRD F18 + CommandBar): find a site by name, or type a date ("13 jan 2027",
// "next month", "2027-03", "+3d"). A date moves the plan's search (with a site selected) or the
// Moon's clock (without one). Typing is always an alternative, never required.
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReferenceSite } from '../data/source';
import { shortName } from '../engine/pins';
import { parseWhen, type When } from '../state/when';

export type Command =
  | { kind: 'site'; site: ReferenceSite }
  | { kind: 'date'; when: When }
  | { kind: 'action'; id: 'proof' | 'home' | 'now' | 'grid' | 'earth'; label: string };

type Props = {
  sites: ReferenceSite[];
  selectedName: string | null;
  onRun: (c: Command) => void;
  onClose: () => void;
};

const ACTIONS: Extract<Command, { kind: 'action' }>[] = [
  { kind: 'action', id: 'proof', label: 'Evidence: our shadows vs LRO photos, real missions, JPL Horizons' },
  { kind: 'action', id: 'now', label: 'Back to now' },
  { kind: 'action', id: 'home', label: 'Whole Moon' },
  { kind: 'action', id: 'earth', label: 'View from Earth (the phase in your sky)' },
  { kind: 'action', id: 'grid', label: 'Toggle latitude/longitude grid' },
];

function score(q: string, s: ReferenceSite): number {
  const name = s.name.toLowerCase(), group = (s.group ?? '').toLowerCase();
  if (name.startsWith(q)) return 3;
  if (name.split(/[\s(]+/).some((w) => w.startsWith(q))) return 2;
  if (name.includes(q) || group.includes(q)) return 1;
  return 0;
}

export function CommandBar({ sites, selectedName, onRun, onClose }: Props) {
  const [q, setQ] = useState('');
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { input.current?.focus(); }, []);

  const items = useMemo<Command[]>(() => {
    const t = q.trim().toLowerCase();
    const when = t ? parseWhen(t, Date.now()) : null;
    const hits = t ? sites.map((s) => ({ s, k: score(t, s) })).filter((x) => x.k > 0).sort((a, b) => b.k - a.k).map((x) => x.s) : sites.slice(0, 0);
    const acts = t ? ACTIONS.filter((a) => a.label.toLowerCase().includes(t)) : ACTIONS;
    return [
      ...(when ? [{ kind: 'date', when } as Command] : []),
      ...hits.slice(0, 8).map((site) => ({ kind: 'site', site }) as Command),
      ...acts,
    ];
  }, [q, sites]);
  useEffect(() => setI(0), [q]);

  const run = (c: Command | undefined) => { if (c) { onRun(c); onClose(); } };

  return (
    <div className="la-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="la-cmd" role="dialog" aria-label="Search sites, dates and actions">
        <input ref={input} value={q} placeholder="Shackleton · 13 jan 2027 · next month · 2027-03 · +10d"
          aria-label="Search" aria-controls="la-cmd-list" aria-activedescendant={items[i] ? `la-cmd-${i}` : undefined}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setI((k) => Math.min(items.length - 1, k + 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setI((k) => Math.max(0, k - 1)); }
            else if (e.key === 'Enter') { e.preventDefault(); run(items[i]); }
            else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
          }} />
        <ul id="la-cmd-list" role="listbox">
          {items.map((c, k) => (
            <li key={k} id={`la-cmd-${k}`} role="option" aria-selected={k === i} className={k === i ? 'on' : undefined}
              onMouseEnter={() => setI(k)} onClick={() => run(c)}>
              {c.kind === 'date' && <><span className="la-cap">Date</span>
                <span>{selectedName ? `Search landings at ${shortName(selectedName)} from ${c.when.label}` : `Show the Moon on ${c.when.label}`}</span>
                <small>{c.when.precision === 'instant' ? 'now' : new Date(c.when.ms).toISOString().slice(0, 10)} UTC</small></>}
              {c.kind === 'site' && <><span className="la-cap">Site</span><span>{c.site.name}</span>
                <small>{Math.abs(c.site.latitude_deg).toFixed(2)}°{c.site.latitude_deg < 0 ? 'S' : 'N'}</small></>}
              {c.kind === 'action' && <><span className="la-cap">Go</span><span>{c.label}</span></>}
            </li>
          ))}
          {!items.length && <li><span className="la-cap">—</span><span className="la-note">Nothing matches. Try a site name or a date like “13 jan 2027”.</span></li>}
        </ul>
        <div className="la-cmd-foot"><span>↑↓ choose</span><span>Enter open</span><span>Esc close</span><span>Dates are UTC days</span></div>
      </div>
    </div>
  );
}
