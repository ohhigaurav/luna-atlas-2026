// Typed dates for the command bar (PRD F18: "13 jan 2027", "next month", "2027-03").
// Pure and UTC-based: a day means 00:00 UTC of that day, a month its first day. Returns null for
// anything it does not understand; it never guesses between day-first and month-first numerals.

export type When = { ms: number; label: string; precision: 'instant' | 'day' | 'month' | 'year' };

const DAY = 86400e3;
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const midnight = (ms: number) => { const d = new Date(ms); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); };
const dayLabel = (ms: number) => { const d = new Date(ms); return `${d.getUTCDate()} ${MONTH_NAMES[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
const monthLabel = (ms: number) => { const d = new Date(ms); return `${MONTH_NAMES[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };

const FULL = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
/** "jan", "Jan.", "janu", "january" -> 0; anything else -> null. */
function month(word: string): number | null {
  const w = word.toLowerCase().replace(/\.$/, '');
  if (w.length < 3) return null;
  const i = FULL.findIndex((f) => f.startsWith(w));
  return i < 0 ? null : i;
}

/** A valid UTC date or null (rejects 31 Feb and friends). */
function ymd(y: number, m: number, d: number): number | null {
  if (y < 1900 || y > 2200 || m < 0 || m > 11 || d < 1 || d > 31) return null;
  const ms = Date.UTC(y, m, d);
  return new Date(ms).getUTCDate() === d ? ms : null;
}

const day = (ms: number | null): When | null => (ms === null ? null : { ms, label: dayLabel(ms), precision: 'day' });
const mon = (ms: number | null): When | null => (ms === null ? null : { ms, label: monthLabel(ms), precision: 'month' });

export function parseWhen(input: string, nowMs: number): When | null {
  const t = input.trim().toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ');
  if (!t) return null;
  const today = midnight(nowMs), now = new Date(nowMs);
  const Y = now.getUTCFullYear(), M = now.getUTCMonth();

  if (t === 'now') return { ms: nowMs, label: 'Now', precision: 'instant' };
  if (t === 'today') return day(today);
  if (t === 'tomorrow') return day(today + DAY);
  if (t === 'next week') return day(today + 7 * DAY);
  if (t === 'next month') return mon(Date.UTC(Y, M + 1, 1));
  if (t === 'next year') return { ms: Date.UTC(Y + 1, 0, 1), label: String(Y + 1), precision: 'year' };

  // +3d, 3 days, in 2 weeks, +1 month
  let m = t.match(/^(?:\+|in )?\s*(\d{1,4})\s*(d|days?|w|wks?|weeks?|mo|months?|y|yrs?|years?)$/);
  if (m) {
    const n = Number(m[1]), u = m[2][0];
    if (u === 'd') return day(today + n * DAY);
    if (u === 'w') return day(today + 7 * n * DAY);
    // Months and years keep the day of the month, clamped to the month's length (31 Jan + 1 mo = 28/29 Feb).
    const d = new Date(today), add = u === 'y' ? 12 * n : n;
    const y = d.getUTCFullYear() + Math.floor((d.getUTCMonth() + add) / 12), mo = (d.getUTCMonth() + add) % 12;
    const last = new Date(Date.UTC(y, mo + 1, 0)).getUTCDate();
    return day(ymd(y, mo, Math.min(d.getUTCDate(), last)));
  }

  // ISO: 2027-03-15, 2027-03, 2027
  if ((m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) return day(ymd(+m[1], +m[2] - 1, +m[3]));
  if ((m = t.match(/^(\d{4})-(\d{1,2})$/))) return mon(+m[2] >= 1 && +m[2] <= 12 ? Date.UTC(+m[1], +m[2] - 1, 1) : null);
  if ((m = t.match(/^(\d{4})$/)) && +m[1] >= 1900 && +m[1] <= 2200) return { ms: Date.UTC(+m[1], 0, 1), label: m[1], precision: 'year' };

  const parts = t.split(' ');
  // 13 jan 2027 · jan 13 2027 · 13 jan · jan 13
  if (parts.length === 3 || parts.length === 2) {
    const [a, b, c] = parts;
    let d: number | null = null, mo: number | null = null, y: number | null = null;
    if (/^\d{1,2}(st|nd|rd|th)?$/.test(a) && month(b) !== null) { d = parseInt(a, 10); mo = month(b); }
    else if (month(a) !== null && /^\d{1,2}(st|nd|rd|th)?$/.test(b)) { d = parseInt(b, 10); mo = month(a); }
    else if (month(a) !== null && /^\d{4}$/.test(b) && parts.length === 2) return mon(Date.UTC(+b, month(a)!, 1)); // jan 2027
    if (d !== null && mo !== null) {
      if (c !== undefined) { if (!/^\d{4}$/.test(c)) return null; y = +c; return day(ymd(y, mo, d)); }
      // no year: the next time that date comes round (today counts)
      const thisYear = ymd(Y, mo, d);
      if (thisYear !== null && thisYear >= today) return day(thisYear);
      return day(ymd(Y + 1, mo, d));
    }
  }
  // jan · january: the next first-of-month with that name (this month counts)
  if (parts.length === 1 && month(parts[0]) !== null) {
    const mo = month(parts[0])!;
    return mon(Date.UTC(mo >= M ? Y : Y + 1, mo, 1));
  }
  return null;
}
