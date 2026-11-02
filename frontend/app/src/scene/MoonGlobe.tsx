// src/scene/MoonGlobe.tsx — the LROC/LOLA Moon, lit by /api/sky-geometry at the shared cursor time.
// Assets (see scripts/fetch_textures.sh / lola_to_f16.py):
//   public/textures/lroc_color_2k.jpg      SVS 4720 colour, 2048x1024, centred on 0 deg longitude
//   public/textures/lola_4ppd_f16.bin      SVS 4720 ldem_4 converted by scripts/lola_to_f16.py (1440x720)
import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame, useLoader, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { createLunarMaterial, loadLolaHeights, updateLunarMaterial } from './lunarMaterial';
import { sampleTimesMs, skyAt, type SkyGeometry } from '../api/sky';

const COLOR_URL = '/textures/lroc_color_2k.jpg';
const HEIGHT_URL = '/textures/lola_4ppd_f16.bin';
const HEIGHT_W = 1440;
const HEIGHT_H = 720;

type Props = {
  sky: SkyGeometry;
  /** Read the cursor without re-rendering, e.g. () => Date.parse(useStore.getState().cursorUtc ?? sky.settings.start_utc) */
  getCursorMs: () => number;
  radius?: number;
};

export function MoonGlobe({ sky, getCursorMs, radius = 1 }: Props) {
  const color = useLoader(THREE.TextureLoader, COLOR_URL);
  const gl = useThree((s) => s.gl);
  const [heights, setHeights] = useState<THREE.DataTexture | null>(null);
  const mesh = useRef<THREE.Mesh>(null);

  useEffect(() => {
    color.colorSpace = THREE.SRGBColorSpace;            // the SVS JPEG/TIFFs are sRGB-encoded
    color.wrapS = THREE.RepeatWrapping;                 // the shader samples across the 180 deg seam
    color.anisotropy = gl.capabilities.getMaxAnisotropy();
    color.needsUpdate = true;
  }, [color, gl]);

  useEffect(() => {
    let alive = true;
    let tex: THREE.DataTexture | undefined;
    loadLolaHeights(HEIGHT_URL, HEIGHT_W, HEIGHT_H).then(
      (t) => { if (alive) { tex = t; setHeights(t); } else t.dispose(); },
      (err) => console.error('LOLA heights failed to load; globe stays unshaded', err),
    );
    return () => { alive = false; tex?.dispose(); };
  }, []);

  const times = useMemo(() => sampleTimesMs(sky), [sky]);

  const material = useMemo(() => {
    if (!heights) return null;
    const s = skyAt(sky, times, getCursorMs());
    return createLunarMaterial({
      colorMap: color, dispMap: heights,
      sunDirMe: s.sunDir, earthDirMe: s.earthDir, earthIllumFrac: s.earthIllumFrac,
    });
    // sky/times change only the per-frame uniforms, so they are not dependencies here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [color, heights]);
  useEffect(() => () => material?.dispose(), [material]);

  useFrame(({ camera }) => {
    if (!material || !mesh.current) return;
    const s = skyAt(sky, times, getCursorMs());
    updateLunarMaterial(material, mesh.current, camera, s.sunDir, s.earthDir, s.earthIllumFrac);
  });

  return (
    <mesh ref={mesh} material={material ?? undefined}>
      {/* UVs from the geometry are unused: the shader derives lat/lon from the normal. */}
      <sphereGeometry args={[radius, 192, 96]} />
      {!material && <meshBasicMaterial color="#2a2f3a" />}
    </mesh>
  );
}
