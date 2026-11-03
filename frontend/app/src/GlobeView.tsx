// Mounts the three.js GlobeEngine once and keeps React out of the render loop. The engine reads
// the shared clock through cursorRef (no re-render per frame); React only hears about selection,
// the end of the opening shot and errors.
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import { GlobeEngine, type SkySample } from './engine/GlobeEngine';
import type { PinSite } from './engine/pins';
import { sampleTimesMs, skyAt, type SkyGeometry } from './api/sky';

export type GlobeHandle = { flyToSite: (s: PinSite) => void; flyHome: () => void; skipIntro: () => void };

type Props = {
  sites: PinSite[];
  sky: SkyGeometry;
  cursorRef: { current: number };
  reducedMotion: boolean;
  onSelect: (s: PinSite | null) => void;
  onIntroDone: () => void;
  onError: (message: string) => void;
  handle: Ref<GlobeHandle>;
};

const T = `${import.meta.env.BASE_URL}textures/`;

/** public/textures/textures.json, written by scripts/fetch_textures.sh: the maps that exist. */
type TextureSet = {
  set?: string;
  moon_color: { file: string; width: number }[];
  heights: { file: string; width: number; height: number };
  caps?: { south: string; north: string; size: number; lat: number } | null;
  earth?: string | null;
};

const FULL_SET: TextureSet = {
  moon_color: [{ file: 'moon_color_8k.jpg', width: 8192 }, { file: 'moon_color_4k.jpg', width: 4096 }],
  heights: { file: 'lola_16ppd_f16_mips.bin', width: 5760, height: 2880 },
  caps: { south: 'lola_cap_s_f16_mips.bin', north: 'lola_cap_n_f16_mips.bin', size: 1536, lat: 75 },
  earth: 'earth_bluemarble_5400.jpg',
};

async function loadTextureSet(): Promise<TextureSet> {
  try {
    const r = await fetch(`${T}textures.json`);
    if (r.ok) return (await r.json()) as TextureSet;
  } catch { /* fall through to the full set */ }
  return FULL_SET;
}

function maxTextureSize(): number {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    const max = gl ? (gl.getParameter(gl.MAX_TEXTURE_SIZE) as number) : 4096;
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return max;
  } catch {
    return 4096;
  }
}

/** The largest colour map this GPU can hold (8k is sharp to ~20 px per degree). */
function pickColor(set: TextureSet): string {
  const max = maxTextureSize();
  const sorted = [...set.moon_color].sort((a, b) => b.width - a.width);
  return `${T}${(sorted.find((c) => c.width <= max) ?? sorted[sorted.length - 1]).file}`;
}

export function GlobeView({ sites, sky, cursorRef, reducedMotion, onSelect, onIntroDone, onError, handle }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<GlobeEngine | null>(null);
  const cb = useRef({ onSelect, onIntroDone, onError });
  cb.current = { onSelect, onIntroDone, onError };

  useImperativeHandle(handle, () => ({
    flyToSite: (s) => engine.current?.flyToSite(s),
    flyHome: () => engine.current?.flyHome(),
    skipIntro: () => engine.current?.skip(),
  }), []);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let cancelled = false;
    const times = sampleTimesMs(sky);
    const sample = (ms: number): SkySample => {
      const s = skyAt(sky, times, ms);
      return { sunDir: s.sunDir, earthDir: s.earthDir, earthIllumFrac: s.earthIllumFrac, earthDistanceKm: s.earthDistanceKm };
    };
    loadTextureSet().then((set) => {
      if (cancelled) return;
      engine.current = new GlobeEngine(el, {
        sites,
        sky: sample,
        cursorMs: () => cursorRef.current,
        reducedMotion,
        textures: {
          moonColor: pickColor(set),
          moonHeights: { url: `${T}${set.heights.file}`, width: set.heights.width, height: set.heights.height },
          moonCaps: set.caps
            ? { south: `${T}${set.caps.south}`, north: `${T}${set.caps.north}`, size: set.caps.size, latDeg: set.caps.lat }
            : undefined,
          earthDay: set.earth ? `${T}${set.earth}` : undefined,
        },
        onSelect: (s) => cb.current.onSelect(s),
        onIntroDone: () => cb.current.onIntroDone(),
        onError: (m) => cb.current.onError(m),
      });
    });
    return () => { cancelled = true; engine.current?.dispose(); engine.current = null; };
  }, [sites, sky, cursorRef, reducedMotion]);

  return <div ref={host} className="la-stage" />;
}
