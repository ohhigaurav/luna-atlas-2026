import { describe, expect, it } from 'vitest';
import { anchorFor } from '../src/plan/useOutlook';

const T = (s: string) => Date.parse(s);
const mid = (ms: number) => { const d = new Date(ms); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); };
const NOW = T('2026-11-08T07:30:00Z');

describe('which day the pins answer for', () => {
  it('stays on today when the date bar is within a day of now', () => {
    expect(anchorFor(T('2026-11-09T01:00:00Z'), NOW, mid)).toEqual({ dayMs: T('2026-11-08T00:00:00Z'), atMs: NOW, searchMs: T('2026-11-08T00:00:00Z') });
  });
  it("reuses today's 90-day search while it covers the next 30 days from the date bar", () => {
    const a = anchorFor(T('2026-11-28T12:00:00Z'), NOW, mid);
    expect(a).toEqual({ dayMs: T('2026-11-28T00:00:00Z'), atMs: T('2026-11-28T12:00:00Z'), searchMs: T('2026-11-08T00:00:00Z') });
  });
  it("searches from the date bar's own day when today's search would not cover 30 days, or for a past date", () => {
    expect(anchorFor(T('2027-01-20T00:00:00Z'), NOW, mid).searchMs).toBe(T('2027-01-20T00:00:00Z'));
    expect(anchorFor(T('2026-10-01T05:00:00Z'), NOW, mid).searchMs).toBe(T('2026-10-01T00:00:00Z'));
  });
});
