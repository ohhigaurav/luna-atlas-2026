// Share links (task 4): the open site, the date, the mission length and the compare set live in the
// address bar (history.replaceState), and a link with them opens the app in that state.
//   ?site=reference-lola-site-001&t=2027-08-01T00:00Z&m=7&cmp=a;b;c&view=compare
// Clicked points keep their app ID ("point:-89.4500,223.2000", hence ';' between compare places).
// No t means "now" (the live clock).

export type View = 'compare' | 'evidence';
export type ShareState = {
  siteId: string | null;
  /** null = following the live clock. */
  ms: number | null;
  missionDays: number | null;
  cmp: string[];
  view: View | null;
  /** ?tour=plan or ?tour=pole starts that tour chapter (a link for the submission or the video). */
  tour?: 'plan' | 'pole' | null;
};

const VIEWS: View[] = ['compare', 'evidence'];
const MAX_CMP = 6;

/** Minute precision, UTC, without seconds: "2027-08-01T00:00Z". */
export function minuteIso(ms: number): string {
  return `${new Date(Math.floor(ms / 60e3) * 60e3).toISOString().slice(0, 16)}Z`;
}

export function encodeShare(s: ShareState): string {
  const p = new URLSearchParams();
  if (s.siteId) p.set('site', s.siteId);
  if (s.ms !== null) p.set('t', minuteIso(s.ms));
  if (s.missionDays !== null) p.set('m', String(s.missionDays));
  if (s.cmp.length) p.set('cmp', s.cmp.slice(0, MAX_CMP).join(';'));
  if (s.view) p.set('view', s.view);
  if (s.tour) p.set('tour', s.tour);
  // URLSearchParams escapes ':', ',' and ';'; all are legal in a query, so keep links readable.
  const q = p.toString().replace(/%3A/gi, ':').replace(/%2C/gi, ',').replace(/%3B/gi, ';');
  return q ? `?${q}` : '';
}

/** Reads a query string; anything malformed is dropped, never guessed. */
export function decodeShare(search: string): ShareState {
  const p = new URLSearchParams(search);
  const site = p.get('site')?.trim() || null;
  const tRaw = p.get('t');
  const t = tRaw ? Date.parse(/Z$|[+-]\d\d:?\d\d$/.test(tRaw) ? tRaw : `${tRaw}Z`) : NaN;
  const m = Number(p.get('m'));
  const view = p.get('view') as View | null;
  const tour = p.get('tour');
  const cmp = [...new Set((p.get('cmp') ?? '').split(';').map((x) => x.trim()).filter(Boolean))].slice(0, MAX_CMP);
  return {
    siteId: site,
    ms: Number.isFinite(t) ? t : null,
    missionDays: Number.isInteger(m) && m >= 1 && m <= 14 ? m : null,
    cmp,
    view: view && VIEWS.includes(view) ? view : null,
    tour: tour === 'plan' || tour === 'pole' ? tour : null,
  };
}

/** Does the link ask for anything? (Then the first-visit tour waits for the Tour button.) */
export function hasShare(s: ShareState): boolean {
  return !!(s.siteId || s.ms !== null || s.cmp.length || s.view || s.tour);
}
