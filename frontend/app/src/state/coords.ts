// Typed coordinates for Ctrl K (challenge O1b): "-89.45, 223.2", "89.45S 223.2E", "89.45 S, 136.8 W",
// "89.45° S 223.2° E". Latitude first. Longitude is returned east, in [0, 360).
export function parseCoords(text: string): { lat: number; lon: number } | null {
  const m = /^\s*([+-]?\d+(?:\.\d+)?)\s*°?\s*([nsNS])?\s*[,;\s]\s*([+-]?\d+(?:\.\d+)?)\s*°?\s*([ewEW])?\s*$/.exec(text.replace(/,\s*/g, ', '));
  if (!m) return null;
  let lat = Number(m[1]), lon = Number(m[3]);
  const ns = m[2]?.toUpperCase(), ew = m[4]?.toUpperCase();
  if (ns && lat < 0) return null;            // "-89 S" is ambiguous: refuse rather than guess
  if (ew && lon < 0) return null;
  if (ns === 'S') lat = -lat;
  if (ew === 'W') lon = -lon;
  if (!(Math.abs(lat) <= 90) || !(Math.abs(lon) <= 360)) return null;
  if (!ns && !ew && !/[.,]/.test(text)) return null;   // "2027 3" is not a place
  return { lat, lon: Math.round((((lon % 360) + 360) % 360) * 1e6) / 1e6 };
}
