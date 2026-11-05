import { describe, expect, it } from 'vitest';
import { parseWhen } from '../src/state/when';

const NOW = Date.parse('2026-11-04T09:14:00Z');
const d = (s: string) => Date.parse(`${s}T00:00:00Z`);
const p = (s: string) => parseWhen(s, NOW);

describe('parseWhen', () => {
  it('reads day-month-year and month-day-year words', () => {
    expect(p('13 jan 2027')?.ms).toBe(d('2027-01-13'));
    expect(p('Jan 13, 2027')?.ms).toBe(d('2027-01-13'));
    expect(p('13 January 2027')?.label).toBe('13 Jan 2027');
    expect(p('3rd mar 2028')?.ms).toBe(d('2028-03-03'));
  });
  it('rolls a date without a year to its next occurrence (today counts)', () => {
    expect(p('13 jan')?.ms).toBe(d('2027-01-13'));
    expect(p('4 nov')?.ms).toBe(d('2026-11-04'));
    expect(p('1 nov')?.ms).toBe(d('2027-11-01'));
  });
  it('reads ISO days, months and years', () => {
    expect(p('2027-03-15')?.ms).toBe(d('2027-03-15'));
    expect(p('2027-03')).toEqual({ ms: d('2027-03-01'), label: 'Mar 2027', precision: 'month' });
    expect(p('2028')?.ms).toBe(d('2028-01-01'));
    expect(p('jan 2027')?.precision).toBe('month');
  });
  it('reads relative phrases', () => {
    expect(p('today')?.ms).toBe(d('2026-11-04'));
    expect(p('tomorrow')?.ms).toBe(d('2026-11-05'));
    expect(p('next month')?.ms).toBe(d('2026-12-01'));
    expect(p('next year')?.ms).toBe(d('2027-01-01'));
    expect(p('+3d')?.ms).toBe(d('2026-11-07'));
    expect(p('in 2 weeks')?.ms).toBe(d('2026-11-18'));
    expect(p('3 months')?.ms).toBe(d('2027-02-04'));
    expect(p('now')?.ms).toBe(NOW);
  });
  it('clamps month arithmetic to the month length', () => {
    expect(parseWhen('+1 month', Date.parse('2027-01-31T12:00:00Z'))?.ms).toBe(d('2027-02-28'));
  });
  it('rejects impossible or ambiguous input', () => {
    expect(p('31 feb 2027')).toBe(null);
    expect(p('13/01/2027')).toBe(null);
    expect(p('shackleton')).toBe(null);
    expect(p('2027-13')).toBe(null);
    expect(p('ma')).toBe(null);
  });
});
