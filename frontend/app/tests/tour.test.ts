import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CHAPTERS, TOUR_DATE_UTC } from '../src/tour/steps';

// Honesty rule for the tour: every number in a caption is either in that step's evidence quote,
// which must really be in the evidence file, or listed here with the reason it needs no evidence.
const repo = new URL('../../../', import.meta.url);
const flat = (s: string) => s.replace(/\s+/g, ' ');
const NOT_MEASURED: Record<string, string> = {
  '001': 'site name', '004': 'site name',
  '29.5': 'standard figure, linked to NASA on the step', '5 m': 'terrain map resolution label',
  '240 m': 'terrain map resolution label', 'Nov 2026': 'date of the Malapert run, in the quote\'s file',
  '2027': 'year of the Gate P runs, in the quote\'s file', 'Jan 2027': 'Gate P row date', 'Gate B': 'name', 'Gate S': 'name', 'Gate P': 'name',
};

describe('guided tour', () => {
  it('has 4 to 6 steps per chapter, each with a target and an action', () => {
    for (const c of CHAPTERS) {
      expect(c.steps.length >= 4 && c.steps.length <= 6).toBe(true);
      for (const s of c.steps) expect(!!s.target && !!s.action.kind).toBe(true);
    }
    expect(Number.isNaN(Date.parse(TOUR_DATE_UTC))).toBe(false);
  });
  it('quotes each source exactly as it is written in the evidence file', () => {
    for (const s of CHAPTERS.flatMap((c) => c.steps)) {
      for (const q of s.sources ?? []) {
        expect(flat(readFileSync(new URL(q.file, repo), 'utf8'))).toContain(flat(q.quote));
      }
    }
  });
  it('uses no number that is not in a source quote or explained above', () => {
    for (const s of CHAPTERS.flatMap((c) => c.steps)) {
      let body = s.body;
      for (const k of Object.keys(NOT_MEASURED).sort((a, b) => b.length - a.length)) body = body.split(k).join(' ');
      const quotes = flat((s.sources ?? []).map((q) => q.quote).join(' ')).replace(/−/g, '-');
      const nums = body.match(/\d+(?:\.\d+)?/g) ?? [];
      for (const n of nums) {
        // Rounded forms of a quoted number are fine (−7.54° shown as −7.5°).
        const ok = quotes.includes(n) || (quotes.match(/\d+(?:\.\d+)?/g) ?? []).some((q) => Number(q).toFixed(n.split('.')[1]?.length ?? 0) === n);
        expect(`${s.id}: ${n} ${ok ? 'sourced' : 'NOT SOURCED'}`).toBe(`${s.id}: ${n} sourced`);
      }
    }
  });
  it('links the 29.5-day lunar day to NASA', () => {
    const s = CHAPTERS.flatMap((c) => c.steps).find((x) => x.body.includes('29.5'))!;
    expect(s.link?.href.startsWith('https://svs.gsfc.nasa.gov/')).toBe(true);
  });
});
