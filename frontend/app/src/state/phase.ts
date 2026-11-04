// How much of the Moon is lit as seen from Earth, from the backend's Sun and Earth directions.
// Phase angle at the Moon a = angle(Moon->Sun, Moon->Earth); lit fraction k = (1 + cos a) / 2
// (Meeus, Astronomical Algorithms, ch. 48). Only restates /api/sky-geometry vectors.

type Vec3 = readonly [number, number, number];

export type MoonPhase = { fraction: number; waxing: boolean; name: string };

export function litFraction(sunDir: Vec3, earthDir: Vec3): number {
  const c = sunDir[0] * earthDir[0] + sunDir[1] * earthDir[1] + sunDir[2] * earthDir[2];
  return Math.min(1, Math.max(0, (1 + c) / 2));
}

/** Name the phase from the lit fraction and whether it is growing (fraction an hour later). */
export function moonPhase(fraction: number, fractionLater: number): MoonPhase {
  const waxing = fractionLater >= fraction;
  let name: string;
  if (fraction < 0.03) name = 'New Moon';
  else if (fraction > 0.97) name = 'Full Moon';
  else if (Math.abs(fraction - 0.5) <= 0.03) name = waxing ? 'First quarter' : 'Last quarter';
  else if (fraction < 0.5) name = waxing ? 'Waxing crescent' : 'Waning crescent';
  else name = waxing ? 'Waxing gibbous' : 'Waning gibbous';
  return { fraction, waxing, name };
}
