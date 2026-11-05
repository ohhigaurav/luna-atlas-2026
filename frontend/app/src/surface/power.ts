// F20 "Keep the lander alive": an ILLUSTRATIVE power model, shown on screen as such (PRD).
// Sunlight comes from the run's series (the backend's Sun elevation and terrain/flat visibility);
// the panel, battery and load are the player's choices, not any real lander's.
//   flat panel on the deck:   P = P_rated * max(0, sin el)
//   upright, Sun-tracking:    P = P_rated * cos el
//   either one: 0 when the Sun's upper limb is behind the horizon
// The battery starts full, is clamped to [0, capacity], and the lander dies when it reaches 0.

export type PanelKind = 'flat' | 'tracking';
export type PowerParams = { panelW: number; panel: PanelKind; batteryWh: number; loadW: number };
export type SunSample = { tMs: number; sunElDeg: number; sunVisible: boolean };

export type PowerResult = {
  tMs: Float64Array;
  socWh: Float64Array;          // battery charge at each sample time
  diedMs: number | null;        // first moment the battery is empty (interpolated)
  aliveH: number;               // hours from start to death, or to the end of the series
  aliveIsLowerBound: boolean;   // still alive when the series ended
  endMs: number;
};

export function panelPowerW(p: Pick<PowerParams, 'panelW' | 'panel'>, sunElDeg: number, sunVisible: boolean): number {
  if (!sunVisible) return 0;
  const el = (sunElDeg * Math.PI) / 180;
  return p.panel === 'flat' ? p.panelW * Math.max(0, Math.sin(el)) : p.panelW * Math.max(0, Math.cos(el));
}

/** Integrate from startMs (samples before it are skipped). Each step uses the mean of its two ends. */
export function simulate(samples: SunSample[], p: PowerParams, startMs: number): PowerResult {
  const s = samples.filter((x) => x.tMs >= startMs);
  const n = s.length;
  const tMs = new Float64Array(n), socWh = new Float64Array(n);
  if (!n) return { tMs, socWh, diedMs: null, aliveH: 0, aliveIsLowerBound: true, endMs: startMs };
  let soc = p.batteryWh, died: number | null = null;
  tMs[0] = s[0].tMs; socWh[0] = soc;
  for (let i = 1; i < n; i++) {
    const dtH = (s[i].tMs - s[i - 1].tMs) / 3600e3;
    const net = (panelPowerW(p, s[i - 1].sunElDeg, s[i - 1].sunVisible) + panelPowerW(p, s[i].sunElDeg, s[i].sunVisible)) / 2 - p.loadW;
    let next = soc + net * dtH;
    if (died === null && next <= 0) {
      died = s[i - 1].tMs + (net < 0 ? (soc / -net) * 3600e3 : 0);
    }
    if (died !== null) next = 0;
    soc = Math.min(p.batteryWh, Math.max(0, next));
    tMs[i] = s[i].tMs; socWh[i] = soc;
  }
  const endMs = s[n - 1].tMs;
  return {
    tMs, socWh, diedMs: died, endMs,
    aliveH: ((died ?? endMs) - s[0].tMs) / 3600e3,
    aliveIsLowerBound: died === null,
  };
}

/** Battery charge at an arbitrary time (linear between samples), for the gauge on the shared clock. */
export function socAt(r: PowerResult, tMs: number): number | null {
  const n = r.tMs.length;
  if (!n || tMs < r.tMs[0]) return null;
  if (r.diedMs !== null && tMs >= r.diedMs) return 0;
  if (tMs >= r.tMs[n - 1]) return r.socWh[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (r.tMs[mid] <= tMs) lo = mid; else hi = mid; }
  const f = (tMs - r.tMs[lo]) / (r.tMs[hi] - r.tMs[lo]);
  return r.socWh[lo] + (r.socWh[hi] - r.socWh[lo]) * f;
}
