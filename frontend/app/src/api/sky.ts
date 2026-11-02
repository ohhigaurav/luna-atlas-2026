// src/api/sky.ts — client and time lookup for POST /api/sky-geometry.
// Field names match backend/lunar_core/api_models.py (SkyGeometryResponse, schema 1.0).
// Replace these hand-written types with the generated src/api/types.ts once it exists.

export type Vec3 = [number, number, number];

export type BodyTrack = {
  unit: Vec3[];                 // MOON_ME unit vectors, Moon centre -> body
  distance_km: number[];
  sub_lat_deg: number[];
  sub_lon_east_deg: number[];   // [0, 360)
  angular_radius_deg: number[];
};

export type SkyGeometry = {
  schema_version: '1.0';
  kind: 'sky_geometry';
  frame: string;                // "MOON_ME"
  observer_center: 'MOON';
  aberration_correction: string;
  moon_reference_radius_m: number;
  conventions: Record<string, string>;
  settings: { start_utc: string; end_utc: string; step_min: number; sample_count: number };
  series: {
    utc: string[];
    et_s: number[];
    sun: BodyTrack;
    earth: BodyTrack & { phase_angle_deg: number[]; illuminated_fraction: number[] };
  };
};

export async function fetchSkyGeometry(
  startUtc: string,
  endUtc: string,
  stepMin = 30,
  signal?: AbortSignal,
): Promise<SkyGeometry> {
  const res = await fetch('/api/sky-geometry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start_utc: startUtc, end_utc: endUtc, step_min: stepMin }),
    signal,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(`sky-geometry ${res.status}`), { status: res.status, detail: body.detail });
  }
  const sky = (await res.json()) as SkyGeometry;
  if (sky.frame !== 'MOON_ME') throw new Error(`sky-geometry frame is ${sky.frame}; the scene assumes MOON_ME`);
  return sky;
}

/** Parse the series' UTC strings once; keep the result next to the SkyGeometry. */
export function sampleTimesMs(sky: SkyGeometry): Float64Array {
  return Float64Array.from(sky.series.utc, (u) => Date.parse(u));
}

export type SkyAt = { sunDir: Vec3; earthDir: Vec3; earthIllumFrac: number; earthDistanceKm: number; subsolarLatDeg: number; subsolarLonDeg: number };

/**
 * Sun/Earth state at any instant inside the window, with no allocation-heavy work per frame.
 * Unit vectors are linearly interpolated then renormalised; the backend states this is within
 * 0.01 deg of the sampled direction at a 30 min step. Outside the window it clamps to the ends.
 * The subsolar point is reported from the nearest sample (display only; never interpolate longitude
 * across the 0/360 wrap).
 */
export function skyAt(sky: SkyGeometry, timesMs: Float64Array, tMs: number): SkyAt {
  const n = timesMs.length;
  let i: number;
  if (tMs <= timesMs[0]) i = 0;
  else if (tMs >= timesMs[n - 1]) i = n - 2;
  else {
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (timesMs[mid] <= tMs) lo = mid; else hi = mid; }
    i = lo;
  }
  if (n === 1) i = 0;
  const j = Math.min(i + 1, n - 1);
  const span = timesMs[j] - timesMs[i];
  const f = span > 0 ? Math.min(1, Math.max(0, (tMs - timesMs[i]) / span)) : 0;
  const s = sky.series;
  const lerpUnit = (a: Vec3, b: Vec3): Vec3 => {
    const x = a[0] + (b[0] - a[0]) * f, y = a[1] + (b[1] - a[1]) * f, z = a[2] + (b[2] - a[2]) * f;
    const L = Math.hypot(x, y, z);
    return [x / L, y / L, z / L];
  };
  const k = f < 0.5 ? i : j;
  return {
    sunDir: lerpUnit(s.sun.unit[i], s.sun.unit[j]),
    earthDir: lerpUnit(s.earth.unit[i], s.earth.unit[j]),
    earthIllumFrac: s.earth.illuminated_fraction[i] + (s.earth.illuminated_fraction[j] - s.earth.illuminated_fraction[i]) * f,
    earthDistanceKm: s.earth.distance_km[i] + (s.earth.distance_km[j] - s.earth.distance_km[i]) * f,
    subsolarLatDeg: s.sun.sub_lat_deg[k],
    subsolarLonDeg: s.sun.sub_lon_east_deg[k],
  };
}
