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

/** 8k colour where the GPU allows it (sharp to ~20 px per degree), otherwise 4k. */
function moonColorUrl(): string {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    const max = gl ? (gl.getParameter(gl.MAX_TEXTURE_SIZE) as number) : 0;
    gl?.getExtension('WEBGL_lose_context')?.loseContext();
    return max >= 8192 ? `${T}moon_color_8k.jpg` : `${T}moon_color_4k.jpg`;
  } catch {
    return `${T}moon_color_4k.jpg`;
  }
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
    if (!host.current) return;
    const times = sampleTimesMs(sky);
    const sample = (ms: number): SkySample => {
      const s = skyAt(sky, times, ms);
      return { sunDir: s.sunDir, earthDir: s.earthDir, earthIllumFrac: s.earthIllumFrac, earthDistanceKm: s.earthDistanceKm };
    };
    const e = new GlobeEngine(host.current, {
      sites,
      sky: sample,
      cursorMs: () => cursorRef.current,
      reducedMotion,
      textures: {
        moonColor: moonColorUrl(),
        moonHeights: { url: `${T}lola_16ppd_f16_mips.bin`, width: 5760, height: 2880 },
        moonCaps: { south: `${T}lola_cap_s_f16_mips.bin`, north: `${T}lola_cap_n_f16_mips.bin`, size: 1536, latDeg: 75 },
        earthDay: `${T}earth_bluemarble_5400.jpg`,
      },
      onSelect: (s) => cb.current.onSelect(s),
      onIntroDone: () => cb.current.onIntroDone(),
      onError: (m) => cb.current.onError(m),
    });
    engine.current = e;
    return () => { e.dispose(); engine.current = null; };
  }, [sites, sky, cursorRef, reducedMotion]);

  return <div ref={host} className="la-stage" />;
}
