// Display formats from the PRD ("Time and units, everywhere"). One place, unit-tested.

/** 0-360 east-positive -> "23.47° E" / "36.58° W" (two decimals; 0 and 180 have no hemisphere). */
export function formatLon(lonEastDeg: number): string {
  let l = ((lonEastDeg % 360) + 360) % 360;
  if (l > 180) l -= 360;
  const v = Math.abs(l).toFixed(2);
  if (v === '0.00' || v === '180.00') return `${v}°`;
  return `${v}° ${l > 0 ? 'E' : 'W'}`;
}

/** Planetocentric latitude -> "84.79° S" / "0.67° N". */
export function formatLat(latDeg: number): string {
  const v = Math.abs(latDeg).toFixed(2);
  return v === '0.00' ? '0.00°' : `${v}° ${latDeg > 0 ? 'N' : 'S'}`;
}

/** UTC instant for the expert drawer: "2027-01-14 06:00 UTC". */
export function formatUtc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
}

/** Local time for simple mode: "14 Jan 2027, 11:30" in the viewer's zone. */
export function formatLocal(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
