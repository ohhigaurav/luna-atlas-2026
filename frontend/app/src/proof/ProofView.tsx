// Evidence screen (PRD F22 proof slider, F21 ghost landings as a table, Gate B). The pictures are
// tools/shadow_match.py output copied by tools/export_proof.py; every number is from the evidence
// files (./evidence.ts). The failing frame and the failing mission are shown, not hidden.
import { useEffect, useState } from 'react';
import { HORIZONS, MISSION_EVENTS, MORE_CHECKS, SHADOW_MATCH, type MissionCase } from './evidence';

const REPO_BLOB = 'https://github.com/ohhigaurav/luna-atlas-2026/blob/main/';
import { CloseIcon } from '../ui/Icons';

const BASE = `${import.meta.env.BASE_URL}proof/`;

type Report = { frames?: { frame: string; diagnostics_post_hoc?: { photo_shadow_fraction?: number; lit_iou?: number } }[] };
type Props = { live: boolean; onClose: () => void; onShow: (c: MissionCase) => void };

/** Geometry of a *_compare.png: three square panels separated by 6 px white gaps. */
function useCompare(frame: string) {
  const [img, setImg] = useState<{ url: string; w: number; h: number } | 'missing' | null>(null);
  useEffect(() => {
    let off = false;
    const url = `${BASE}${frame}_compare.png`;
    const im = new Image();
    im.onload = () => { if (!off) setImg({ url, w: im.naturalWidth, h: im.naturalHeight }); };
    im.onerror = () => { if (!off) setImg('missing'); };
    im.src = url;
    return () => { off = true; };
  }, [frame]);
  return img;
}

function Wipe({ frame, mode }: { frame: string; mode: 'wipe' | 'diff' }) {
  const img = useCompare(frame);
  const [x, setX] = useState(50);
  if (img === null) return <div className="la-wipe" aria-busy="true" />;
  if (img === 'missing') {
    return (
      <div className="la-missing">
        <b>The comparison pictures are not on this machine yet.</b>
        <span>They are made by the shadow-match run and copied into the app with:</span>
        <code>python tools/export_proof.py</code>
        <span>The verdict and the table on the right are from the committed evidence file and do not need them.</span>
      </div>
    );
  }
  const n = (img.w - 12) / 3;
  const size = `${(img.w / n) * 100}% 100%`;
  const at = (o: number) => `${(o / (img.w - n)) * 100}% 0`;
  const photo = { backgroundImage: `url(${img.url})`, backgroundSize: size, backgroundPosition: at(0) };
  const ours = { backgroundImage: `url(${img.url})`, backgroundSize: size, backgroundPosition: at(n + 6) };
  const diff = { backgroundImage: `url(${img.url})`, backgroundSize: size, backgroundPosition: at(2 * n + 12) };
  if (mode === 'diff') {
    return (
      <div className="la-wipe" style={{ cursor: 'default' }}>
        <div className="pane" style={diff} role="img" aria-label="Difference: grey agree, red we say lit, blue we say dark, purple not imaged" />
        <span className="lab" style={{ left: 10 }}>Difference</span>
      </div>
    );
  }
  return (
    <div className="la-wipe">
      <div className="pane" style={ours} role="img" aria-label="Our computed shadows" />
      <div className="pane" style={{ ...photo, clipPath: `inset(0 ${100 - x}% 0 0)` }} role="img" aria-label="LRO WAC photo" />
      <span className="lab" style={{ left: 10 }}>LRO photo</span>
      <span className="lab" style={{ right: 10 }}>Luna Atlas shadows</span>
      <div className="divider" style={{ left: `${x}%` }}><span className="grip">⇔</span></div>
      <input type="range" min={0} max={100} step={0.5} value={x} aria-label="Wipe between the LRO photo and our shadows" onChange={(e) => setX(Number(e.target.value))} />
    </div>
  );
}

export function ProofView({ live, onClose, onShow }: Props) {
  const [tab, setTab] = useState<'lro' | 'missions' | 'horizons' | 'more'>('lro');
  const [sel, setSel] = useState(0);
  const [mode, setMode] = useState<'wipe' | 'diff'>('wipe');
  const [report, setReport] = useState<Report | null>(null);
  useEffect(() => {
    fetch(`${BASE}report.json`).then((r) => (r.ok ? r.json() : null)).then(setReport, () => setReport(null));
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  const f = SHADOW_MATCH.frames[sel];
  const diag = report?.frames?.find((r) => r.frame === f.frame)?.diagnostics_post_hoc;

  return (
    <section className="la-sheet" aria-label="Evidence">
      <div className="la-sheet-head">
        <h2>Is it right?</h2>
        <div className="la-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === 'lro'} className={tab === 'lro' ? 'on' : ''} onClick={() => setTab('lro')}>LRO photos · 5/6</button>
          <button type="button" role="tab" aria-selected={tab === 'missions'} className={tab === 'missions' ? 'on' : ''} onClick={() => setTab('missions')}>Real missions · 6/7</button>
          <button type="button" role="tab" aria-selected={tab === 'horizons'} className={tab === 'horizons' ? 'on' : ''} onClick={() => setTab('horizons')}>JPL Horizons</button>
          <button type="button" role="tab" aria-selected={tab === 'more'} className={tab === 'more' ? 'on' : ''} onClick={() => setTab('more')}>Slope, maps, open problems</button>
        </div>
        <span className="la-spacer" />
        <button type="button" className="la-x" style={{ position: 'static' }} aria-label="Close evidence (Esc)" onClick={onClose}><CloseIcon /></button>
      </div>

      {tab === 'lro' && (
        <div className="la-sheet-body">
          <div className="la-sheet-main">
            <div className="la-kv">
              <div><span className="la-cap">Verdict</span><b className="good-c">PASS · {SHADOW_MATCH.verdict}</b></div>
              <div><span className="la-cap">This frame</span><b className={f.pass ? 'good-c' : 'bad-c'}>{f.agreementPct.toFixed(1)}% · IoU {f.shadowIoU.toFixed(2)}</b></div>
              <div><span className="la-cap">Sun</span><b>{f.sunHeightDeg.toFixed(2)}° up, toward {f.sunTowardDegE.toFixed(1)}°E</b></div>
              {diag?.photo_shadow_fraction !== undefined && (
                <div title="What a model that says 'everything is dark' would score on this frame (post hoc diagnostic)">
                  <span className="la-cap">All-dark guess</span><b>{(diag.photo_shadow_fraction * 100).toFixed(1)}%</b>
                </div>
              )}
            </div>
            <div className="la-actions">
              <div className="la-seg" style={{ width: 260 }}>
                <button type="button" className={mode === 'wipe' ? 'on' : ''} onClick={() => setMode('wipe')}>Photo ⇔ ours</button>
                <button type="button" className={mode === 'diff' ? 'on' : ''} onClick={() => setMode('diff')}>Difference</button>
              </div>
              {mode === 'diff' && (
                <div className="la-diff-legend">
                  <span><i style={{ background: '#c8c8c8' }} />agree</span>
                  <span><i style={{ background: '#dc3c3c' }} />we say lit, photo dark</span>
                  <span><i style={{ background: '#3c78e6' }} />we say dark, photo lit</span>
                  <span><i style={{ background: '#3c003c' }} />not imaged</span>
                </div>
              )}
            </div>
            <Wipe frame={f.frame} mode={mode} />
            <p className="la-note">{SHADOW_MATCH.setup}.</p>
            <p className="la-note">{SHADOW_MATCH.caveat}</p>
            <span className="la-cap">Source: {SHADOW_MATCH.file}</span>
          </div>
          <aside className="la-sheet-side">
            <div className="la-sec"><span className="la-cap">Six photos, the Sun from six directions</span><span className="la-note">{SHADOW_MATCH.rule}</span></div>
            <ul className="la-frames">
              {SHADOW_MATCH.frames.map((x, k) => (
                <li key={x.frame}>
                  <button type="button" className={k === sel ? 'on' : ''} onClick={() => setSel(k)} aria-pressed={k === sel}>
                    <b>{x.utc} UTC</b>
                    <span className={`la-verdict ${x.pass ? 'pass' : 'fail'}`}>{x.pass ? 'PASS' : 'FAIL'}</span>
                    <small>Sun toward {x.sunTowardDegE.toFixed(1)}°E · {x.agreementPct.toFixed(1)}% · IoU {x.shadowIoU.toFixed(2)}</small>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}

      {tab === 'missions' && (
        <div className="la-sheet-main">
          <div className="la-kv">
            <div><span className="la-cap">Verdict</span><b>{MISSION_EVENTS.verdict}</b></div>
            <div><span className="la-cap">Rules</span><span className="la-note">fixed in the tool before the first run</span></div>
          </div>
          <table className="la-table">
            <thead><tr><th>Case</th><th>Reported</th><th>Luna Atlas</th><th>Verdict</th><th /></tr></thead>
            <tbody>
              {MISSION_EVENTS.cases.map((c) => (
                <tr key={c.id}>
                  <td>{c.title}{c.note && <div className="la-note" style={{ fontSize: 12, marginTop: 4 }}>{c.note}</div>}</td>
                  <td className="m">{c.reference}</td>
                  <td className="m">{c.model}</td>
                  <td><span className={`la-verdict ${c.pass ? 'pass' : 'fail'}`}>{c.pass ? 'PASS' : 'FAIL'}</span></td>
                  <td>{c.siteId && c.whenUtc && <button type="button" className="la-btn" disabled={!live} title={live ? undefined : 'Needs the live backend'} onClick={() => onShow(c)}>Show the Moon then</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <span className="la-cap">Source: {MISSION_EVENTS.file}</span>
        </div>
      )}

      {tab === 'more' && (
        <div className="la-sheet-main">
          <p className="la-note">Every check had its pass rule written down before the run. Failures and open problems stay on the list.</p>
          <table className="la-table">
            <thead><tr><th>Check</th><th>What we found</th><th>Verdict</th></tr></thead>
            <tbody>
              {MORE_CHECKS.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}<div className="la-note" style={{ fontSize: 12, marginTop: 4 }}><a href={REPO_BLOB + c.file} target="_blank" rel="noreferrer">evidence ↗</a></div></td>
                  <td>{c.text}</td>
                  <td><span className={`la-verdict ${c.verdict === 'PASS' ? 'pass' : 'fail'}`}>{c.verdict}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'horizons' && (
        <div className="la-sheet-main">
          <div className="la-kv"><div><span className="la-cap">Verdict</span><b className="good-c">{HORIZONS.verdict}</b></div></div>
          <p className="la-note" style={{ fontSize: 15, color: 'var(--text)' }}>{HORIZONS.headline}</p>
          <p className="la-note">{HORIZONS.tolerance}</p>
          <span className="la-cap">Source: {HORIZONS.file}</span>
        </div>
      )}
    </section>
  );
}
