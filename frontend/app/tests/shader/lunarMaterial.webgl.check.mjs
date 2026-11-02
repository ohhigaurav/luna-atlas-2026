// Headless WebGL2 check of the MoonGlobe fragment shader (no three.js needed).
// Run: NODE_PATH=$(npm root -g) node tests/shader/lunarMaterial.webgl.check.mjs
// Pass: terminator.wrongBeyond1deg == 0; colour east/north correct; ramp-east brighter under a west Sun.
import { createRequire } from 'module'; const require = createRequire(import.meta.url); const { chromium } = require('playwright');
import fs from 'fs';
const ts = fs.readFileSync(new URL('../../src/scene/lunarMaterial.ts', import.meta.url), 'utf8');
const frag = ts.match(/const frag = \/\* glsl \*\/ `([\s\S]*?)`;/)[1]
  .replace('#include <tonemapping_fragment>', '').replace('#include <colorspace_fragment>', '');
const page = `<!doctype html><canvas id=c width=256 height=256></canvas><script>
const FRAG = ${JSON.stringify(frag)};
const N = 256;
function run(){
  const gl = document.getElementById('c').getContext('webgl2', {preserveDrawingBuffer:true});
  if(!gl) return {error:'no webgl2'};
  const vs = '#version 300 es\\nin vec2 p; out vec2 sp; void main(){ sp=p; gl_Position=vec4(p,0.,1.); }';
  // Wrapper: build the sphere varyings per pixel (orthographic, camera on three +X), then run the PRD shader body.
  const fs = '#version 300 es\\nprecision highp float;\\nout highp vec4 pc_fragColor;\\n#define gl_FragColor pc_fragColor\\nuniform vec3 cameraPosition;\\nin vec2 sp;\\nvec3 vObjN; vec3 vWorldPos;\\n'
    + FRAG.replace(/varying vec3 vObjN;/,'').replace(/varying vec3 vWorldPos;/,'').replace('void main() {', 'void shade() {')
    + '\\nvoid main(){ float r2=dot(sp,sp); if(r2>1.){pc_fragColor=vec4(0.,0.,0.,0.);return;} vObjN=vec3(sqrt(1.-r2), sp.y, -sp.x); vWorldPos=vObjN; shade(); pc_fragColor.a=1.; }';
  function sh(t,src){const s=gl.createShader(t);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
  const pr=gl.createProgram(); gl.attachShader(pr,sh(gl.VERTEX_SHADER,vs)); gl.attachShader(pr,sh(gl.FRAGMENT_SHADER,fs)); gl.linkProgram(pr);
  if(!gl.getProgramParameter(pr,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(pr));
  gl.useProgram(pr);
  const b=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);
  const loc=gl.getAttribLocation(pr,'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
  const U=n=>gl.getUniformLocation(pr,n);
  // float -> half
  const f32=new Float32Array(1), u32=new Uint32Array(f32.buffer);
  function half(v){f32[0]=v;const x=u32[0];const s=(x>>>16)&0x8000;let e=((x>>>23)&0xff)-127+15;let m=(x>>>13)&0x3ff;if(e<=0)return s;if(e>=31)return s|0x7c00;return s|(e<<10)|m;}
  function heightTex(W,H,fn){ // row 0 = south, as lola_to_f16.py writes
    const d=new Uint16Array(W*H); for(let j=0;j<H;j++){const lat=-90+(j+0.5)*180/H; for(let i=0;i<W;i++){const lon=-180+(i+0.5)*360/W; d[j*W+i]=half(fn(lat,lon));}}
    const t=gl.createTexture(); gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D,t);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.R16F,W,H,0,gl.RED,gl.HALF_FLOAT,d);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    gl.uniform1i(U('dispMap'),1); gl.uniform2f(U('texel'),1/W,1/H);
    const R=1737.4; gl.uniform2f(U('kmPerUv'), 2*Math.PI*R, Math.PI*R);
  }
  function colorTex(fn){ // image-like: row 0 = north, uploaded with flipY like three's TextureLoader
    const W=64,H=32,d=new Uint8Array(W*H*4); for(let j=0;j<H;j++){const lat=90-(j+0.5)*180/H; for(let i=0;i<W;i++){const lon=-180+(i+0.5)*360/W; const v=fn(lat,lon); const k=(j*W+i)*4; d[k]=d[k+1]=d[k+2]=v; d[k+3]=255;}}
    const t=gl.createTexture(); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D,t);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
    gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,W,H,0,gl.RGBA,gl.UNSIGNED_BYTE,d);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
    gl.uniform1i(U('colorMap'),0);
  }
  const meToThree=v=>[v[0],v[2],-v[1]];
  const dirME=(lat,lon)=>{const a=lat*Math.PI/180,o=lon*Math.PI/180;return [Math.cos(a)*Math.cos(o),Math.cos(a)*Math.sin(o),Math.sin(a)];};
  function render(sunLatLon, opts={}){
    const s=meToThree(dirME(...sunLatLon));
    gl.uniform3fv(U('sunDir'),s); gl.uniform3fv(U('earthDir'),meToThree(dirME(0,0)));
    gl.uniform1f(U('earthIllum'),0.); gl.uniform1f(U('earthshineGain'),0.); gl.uniform1f(U('L'),opts.L??1.0);
    gl.uniform1f(U('reliefGain'),opts.gain??1.0);
    gl.uniform1f(U('shadowSteps'),opts.shadow??0); gl.uniform1f(U('sunAngRad'),0.2666*Math.PI/180);
    gl.uniformMatrix3fv(U('objToWorldN'),false,[1,0,0,0,1,0,0,0,1]); gl.uniform3f(U('cameraPosition'),1000,0,0);
    gl.viewport(0,0,N,N); gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    const px=new Uint8Array(N*N*4); gl.readPixels(0,0,N,N,gl.RGBA,gl.UNSIGNED_BYTE,px); return px;
  }
  const at=(px,sx,sy)=>{const i=Math.round((sx+1)/2*N-0.5), j=Math.round((sy+1)/2*N-0.5); return px[(j*N+i)*4];};
  const out={};
  // 1) Terminator vs geometry for random suns (flat white albedo, zero heights)
  colorTex(()=>255); heightTex(64,32,()=>0);
  let seed=7; const rnd=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/4294967296);
  let bad=0,checked=0,worst=0;
  for(let k=0;k<12;k++){
    const lat=-90+180*rnd(), lon=-180+360*rnd(); const sME=dirME(lat,lon); const px=render([lat,lon]);
    for(let j=0;j<N;j++)for(let i=0;i<N;i++){
      const sx=(i+0.5)/N*2-1, sy=(j+0.5)/N*2-1, r2=sx*sx+sy*sy; if(r2>0.98) continue;
      const n3=[Math.sqrt(1-r2),sy,-sx], nME=[n3[0],-n3[2],n3[1]];
      const d=nME[0]*sME[0]+nME[1]*sME[1]+nME[2]*sME[2]; const ang=Math.asin(Math.max(-1,Math.min(1,d)))*180/Math.PI;
      const lit=px[(j*N+i)*4]>0; if(Math.abs(ang)<1) continue; checked++;
      if(lit!==(ang>0)){bad++; worst=Math.max(worst,Math.abs(ang));}
    }
  }
  out.terminator={checkedPixels:checked, wrongBeyond1deg:bad, worstDeg:worst};
  // 2) Colour map orientation: east half white, north band grey
  colorTex((lat,lon)=> lon>0?255:40); heightTex(64,32,()=>0);
  let px=render([0,0]); out.colourEastRight={right:at(px,0.5,0), left:at(px,-0.5,0)};
  colorTex((lat,lon)=> lat>0?255:40); px=render([0,0]); out.colourNorthUp={up:at(px,0,0.5), down:at(px,0,-0.5)};
  // 3) Height orientation: a ramp rising to the EAST faces WEST; a west Sun should brighten it
  colorTex(()=>255);
  heightTex(256,128,()=>0); const flatW=at(render([0,-60]),0,0);
  heightTex(256,128,(lat,lon)=> 3*lon); const rampW=at(render([0,-60]),0,0); const rampE=at(render([0,60]),0,0);
  out.slopeEast={flat:flatW, rampWestSun:rampW, rampEastSun:rampE};
  heightTex(256,128,(lat,lon)=> 3*lat); out.slopeNorth={rampSouthSun:at(render([-60,0]),0,0), rampNorthSun:at(render([60,0]),0,0)};
  // 5) Cast shadows: a 5 km wall 0.8-1.6 deg east of the centre (24-48 km away), Sun 6 deg up.
  //    Sun in the east: the wall (9.5-5.9 deg tall seen from the centre) hides it. Sun in the west: no effect.
  heightTex(1440,720,(lat,lon)=> (lon>0.8 && lon<1.6) ? 5 : 0); colorTex(()=>255);
  out.castShadow={eastSunNoShadow:at(render([0,84]),0,0), eastSunShadow:at(render([0,84],{shadow:24}),0,0),
    westSunNoShadow:at(render([0,-84]),0,0), westSunShadow:at(render([0,-84],{shadow:24}),0,0)};
  // 6) Flat ground never shadows itself: terminator check again with shadows on.
  heightTex(64,32,()=>0); colorTex(()=>255);
  { let bad2=0, n2=0; for(let k=0;k<6;k++){ const lat=-80+160*rnd(), lon=-180+360*rnd(); const sME=dirME(lat,lon); const px=render([lat,lon],{shadow:24});
      for(let j=0;j<N;j+=2)for(let i=0;i<N;i+=2){ const sx=(i+0.5)/N*2-1, sy=(j+0.5)/N*2-1, r2=sx*sx+sy*sy; if(r2>0.98) continue;
        const nME=[Math.sqrt(1-r2),sy,-sx].map((v,q,a)=>q===0?a[0]:q===1?-a[2]:a[1]); const d=nME[0]*sME[0]+nME[1]*sME[1]+nME[2]*sME[2];
        const ang=Math.asin(Math.max(-1,Math.min(1,d)))*180/Math.PI; if(Math.abs(ang)<1) continue; n2++; if((px[(j*N+i)*4]>0)!==(ang>0)) bad2++; } }
    out.flatWithShadows={checkedPixels:n2, wrongBeyond1deg:bad2}; }
  // 4) Lommel-Seeliger flatness: brightness near limb vs centre at full phase, L=1 vs L=0
  heightTex(64,32,()=>0); colorTex(()=>255);
  const a=render([0,0],{L:1}); const bL=render([0,0],{L:0});
  out.limbOverCentre={lunarLambert_L1:at(a,0.9,0)/at(a,0,0), lambert_L0:at(bL,0.9,0)/at(bL,0,0)};
  return out;
}
try{ window.RESULT=run(); }catch(e){ window.RESULT={error:String(e)}; }
</script>`;
fs.writeFileSync(new URL('./_t.html', import.meta.url), page);
const browser = await chromium.launch({ args: ['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist'] });
const p = await browser.newPage();
await p.goto(new URL('./_t.html', import.meta.url).href);
await p.waitForFunction(() => window.RESULT !== undefined, null, { timeout: 120000 });
const r = await p.evaluate(() => window.RESULT);
await browser.close();
console.log(JSON.stringify(r, null, 1));
// Pass criteria (from the header): any failure exits non-zero so `npm run check:shader` can gate a merge.
const checks = r.error ? [['shader ran', false, r.error]] : [
  ['terminator: no pixel wrong by more than 1 deg', r.terminator.checkedPixels > 100000 && r.terminator.wrongBeyond1deg === 0, r.terminator],
  ['colour map: east on the right', r.colourEastRight.right > r.colourEastRight.left, r.colourEastRight],
  ['colour map: north up', r.colourNorthUp.up > r.colourNorthUp.down, r.colourNorthUp],
  ['east-rising ramp faces west', r.slopeEast.rampWestSun > r.slopeEast.flat && r.slopeEast.flat > r.slopeEast.rampEastSun, r.slopeEast],
  ['north-rising ramp faces south', r.slopeNorth.rampSouthSun > r.slopeNorth.rampNorthSun, r.slopeNorth],
  ['lunar-Lambert keeps the limb bright (L=1) and Lambert darkens it (L=0)', r.limbOverCentre.lunarLambert_L1 > 0.9 && r.limbOverCentre.lambert_L0 < 0.6, r.limbOverCentre],
  ['a 5 km wall casts a shadow away from a low Sun', r.castShadow.eastSunShadow < 0.1 * r.castShadow.eastSunNoShadow, r.castShadow],
  ['the same wall does not shadow the side facing the Sun', Math.abs(r.castShadow.westSunShadow - r.castShadow.westSunNoShadow) <= 2, r.castShadow],
  ['flat ground never shadows itself', r.flatWithShadows.checkedPixels > 20000 && r.flatWithShadows.wrongBeyond1deg === 0, r.flatWithShadows],
];
for (const [name, ok] of checks) console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`);
process.exit(checks.every(([, ok]) => ok) ? 0 : 1);
