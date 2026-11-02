// src/scene/Canvas.tsx — minimal scene: fetch sky geometry for a window, draw the lit Moon.
// The cursor lives in a ref here; swap it for the Zustand store (cursorUtc) when that exists.
import { Suspense, useEffect, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import * as THREE from 'three';
import { MoonGlobe } from './MoonGlobe';
import { fetchSkyGeometry, type SkyGeometry } from '../api/sky';

const START = '2027-01-01T00:00:00Z';
const END = '2027-01-31T00:00:00Z';

export function MoonScene() {
  const [sky, setSky] = useState<SkyGeometry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cursorMs = useRef(Date.parse(START));

  useEffect(() => {
    const ac = new AbortController();
    fetchSkyGeometry(START, END, 30, ac.signal).then(setSky, (e) => {
      if (e.name !== 'AbortError') setError(typeof e.detail === 'string' ? e.detail : e.message);
    });
    return () => ac.abort();
  }, []);

  if (error) return <p role="alert">Sky geometry unavailable: {error}</p>; // 503 = kernels missing; never fake lighting

  return (
    <>
      <Canvas
        camera={{ position: [0, -0.9, 3.2], fov: 35 }}
        gl={{ toneMapping: THREE.AgXToneMapping, toneMappingExposure: 1.0 }}
        style={{ position: 'fixed', inset: 0, background: '#05070d' }}
      >
        <Stars radius={60} depth={20} count={4000} factor={2} fade speed={0} />
        <Suspense fallback={null}>
          {sky && <MoonGlobe sky={sky} getCursorMs={() => cursorMs.current} />}
        </Suspense>
        <OrbitControls enablePan={false} minDistance={1.4} maxDistance={8} />
      </Canvas>
      {sky && (
        <input
          type="range" aria-label="Time" min={0} max={1000} defaultValue={0}
          style={{ position: 'fixed', left: 24, right: 24, bottom: 24 }}
          onInput={(e) => {
            const a = Date.parse(sky.settings.start_utc), b = Date.parse(sky.settings.end_utc);
            cursorMs.current = a + ((b - a) * Number((e.target as HTMLInputElement).value)) / 1000;
          }}
        />
      )}
    </>
  );
}
