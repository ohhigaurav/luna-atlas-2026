import { describe, expect, it } from 'vitest';
import { decodeShare, encodeShare, hasShare, minuteIso } from '../src/state/shareUrl';

describe('share links', () => {
  it('writes a readable link and reads it back', () => {
    const s = { siteId: 'reference-lola-site-001', ms: Date.parse('2027-08-01T00:00:30Z'), missionDays: 7,
      cmp: ['reference-lola-site-001', 'point:-89.4500,223.2000'], view: 'compare' as const };
    const q = encodeShare(s);
    expect(q).toBe('?site=reference-lola-site-001&t=2027-08-01T00:00Z&m=7&cmp=reference-lola-site-001;point:-89.4500,223.2000&view=compare');
    expect(decodeShare(q)).toEqual({ ...s, ms: Date.parse('2027-08-01T00:00:00Z') });
  });
  it('leaves out what is default: following the clock, no site, default mission', () => {
    expect(encodeShare({ siteId: null, ms: null, missionDays: null, cmp: [], view: null })).toBe('');
    expect(hasShare(decodeShare(''))).toBe(false);
  });
  it('drops anything malformed instead of guessing', () => {
    const d = decodeShare('?t=yesterday&m=99&view=admin&cmp=;;a;a');
    expect(d.ms).toBe(null);
    expect(d.missionDays).toBe(null);
    expect(d.view).toBe(null);
    expect(d.cmp).toEqual(['a']);
  });
  it('reads a time without a zone as UTC, and with an escaped colon', () => {
    expect(decodeShare('?t=2027-08-01T12:00').ms).toBe(Date.parse('2027-08-01T12:00:00Z'));
    expect(decodeShare('?t=2027-08-01T12%3A00Z').ms).toBe(Date.parse('2027-08-01T12:00:00Z'));
    expect(minuteIso(Date.parse('2027-08-01T12:34:56.789Z'))).toBe('2027-08-01T12:34Z');
  });
});
