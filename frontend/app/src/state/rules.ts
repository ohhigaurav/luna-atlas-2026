// Short words for the landing rules (backend landing.py RULE_TEXT keys), for "why not" lines.
export const RULE_SHORT: Record<string, string> = {
  sun_up: 'Sun not up', daylight: 'too little daylight left', earth_up: 'Earth not in view',
  low_sun: 'Sun too high for long shadows', sun_high: 'Sun too low to light the ground',
};
const days = (h: number) => `${(h / 24).toFixed(1)} days`;

export function missText(m: { rules: string[]; daylightH: number; neededH: number }): string {
  return m.rules.map((k) => (k === 'daylight' ? `${days(m.daylightH)} of daylight left, needs ${days(m.neededH)}` : RULE_SHORT[k] ?? k)).join('; ');
}
