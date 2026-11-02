#!/usr/bin/env python3
"""SVS CGI Moon Kit colour TIFF (8- or 16-bit sRGB, 2:1, centred on 0 deg longitude) -> JPEGs.

    python3 scripts/moon_color.py lroc_color_16bit_srgb_8k.tif public/textures/moon_color

writes <prefix>_8k.jpg (when the source is at least 8192 wide) and <prefix>_4k.jpg. The browser
picks 8k when the GPU's MAX_TEXTURE_SIZE allows it. JPEG bytes depend on the Pillow/libjpeg
version, so these outputs are not pinned; the source TIFF is (scripts/sources.sha256).
"""
import sys

import numpy as np
import tifffile
from PIL import Image

src, prefix = sys.argv[1], sys.argv[2]
a = tifffile.imread(src)
if a.ndim != 3 or a.shape[2] < 3 or a.shape[1] != 2 * a.shape[0]:
    sys.exit(f"expected a 2:1 RGB map, got {a.shape}")
if a.dtype == np.uint16:
    a = ((a[:, :, :3].astype(np.uint32) * 255 + 32767) // 65535).astype(np.uint8)
elif a.dtype != np.uint8:
    sys.exit(f"unsupported sample type {a.dtype}")
img = Image.fromarray(np.ascontiguousarray(a[:, :, :3]), "RGB")
sizes = [8192, 4096] if img.width >= 8192 else [4096]
for w in sizes:
    out = img if img.width == w else img.resize((w, w // 2), Image.Resampling.LANCZOS)
    name = f"{prefix}_{w // 1024}k.jpg"
    out.save(name, quality=90, optimize=True, progressive=True)
    print(f"{name}: {w}x{w // 2}")
