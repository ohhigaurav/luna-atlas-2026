/* Local-first, no third-party runtime dependencies. All scientific quantities come from the API. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const state = {
    health: null,
    officialSites: [],
    referenceSites: [],
    terrainCoverage: [],
    currentRun: null,
    currentAnalysis: null,
    currentView: 'compare',
    preview: false,
    selectedSiteId: null,
    cursorIndex: 0,
    finderRun: null,
    savedRuns: [],
    toastTimer: null,
  };

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[ch]);
  const fmt = (value, digits = 2) => Number.isFinite(Number(value))
    ? Number(value).toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
  const fmtHours = (metric) => {
    if (!metric || !Number.isFinite(Number(metric.duration_s))) return '—';
    const hours = Number(metric.duration_s) / 3600;
    const prefix = metric.display_prefix || ((metric.truncated_start || metric.truncated_end) ? '≥ ' : '');
    if (hours >= 48) return `${prefix}${fmt(hours / 24, 2)} d`;
    return `${prefix}${fmt(hours, 2)} h`;
  };
  const fmtPercent = (value) => Number.isFinite(Number(value)) ? `${fmt(Number(value) * 100, 1)}%` : '—';
  // datetime-local controls are browser-local by definition. Convert their instant to UTC
  // explicitly; appending 'Z' to the displayed string silently shifts the analysis interval.
  const utcValue = (id) => {
    const value = $(id).value;
    if (!value) throw new Error(`${id === 'analysisStart' ? 'Start' : 'End'} date/time is required.`);
    const instant = new Date(value);
    if (!Number.isFinite(instant.getTime())) throw new Error(`Invalid date/time for ${id}.`);
    return instant.toISOString().replace(/\.\d{3}Z$/, 'Z');
  };
  const utcToLocalInput = (isoUtc) => {
    const instant = new Date(isoUtc);
    if (!Number.isFinite(instant.getTime())) throw new Error(`Invalid UTC default: ${isoUtc}`);
    return new Date(instant.getTime() - instant.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  };
  const dateUtc = (id, endOfDay = false) => {
    const value = $(id).value;
    if (!value) throw new Error('Both search dates are required.');
    return `${value}T${endOfDay ? '23:59:00' : '00:00:00'}Z`;
  };
  const selectedSites = () => {
    const ids = [...document.querySelectorAll('input[name="siteChoice"]:checked')].map((el) => el.value);
    return ids;
  };
  const allAvailableSites = () => state.officialSites.length ? state.officialSites : state.referenceSites;
  const siteById = (id) => allAvailableSites().find((site) => site.site_id === id)
    || state.currentAnalysis?.sites?.map((item) => item.site).find((site) => site.site_id === id)
    || state.currentAnalysis?.site_results?.map((item) => item.site).find((site) => site.site_id === id)
    || state.currentRun?.sites?.map((item) => item.site).find((site) => site.site_id === id)
    || state.currentRun?.site_results?.map((item) => item.site).find((site) => site.site_id === id);
  const currentAnalysisSites = () => state.currentAnalysis?.sites || state.currentAnalysis?.site_results || [];
  const selectedAnalysisSite = () => currentAnalysisSites().find((item) => item.site.site_id === state.selectedSiteId)
    || currentAnalysisSites()[0] || null;

  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
    const contentType = response.headers.get('content-type') || '';
    let body;
    if (contentType.includes('application/json')) body = await response.json();
    else body = await response.text();
    if (!response.ok) {
      const detail = body && typeof body === 'object' ? (body.detail || body.message || JSON.stringify(body)) : body;
      throw new Error(`${response.status} ${response.statusText}: ${detail || 'Request failed'}`);
    }
    return body;
  }

  function toast(message, kind = 'info') {
    const el = $('toast');
    el.textContent = message;
    el.dataset.kind = kind;
    el.classList.add('visible');
    if (state.toastTimer) window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => el.classList.remove('visible'), 4200);
  }

  function setMessage(id, message, kind = '') {
    const el = $(id);
    if (!el) return;
    el.textContent = message;
    el.className = `form-message visible${kind ? ` ${kind}` : ''}`;
  }

  function showView(name) {
    state.currentView = name;
    document.querySelectorAll('.view').forEach((el) => el.classList.toggle('active', el.id === `view-${name}`));
    document.querySelectorAll('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.view === name));
    const names = { compare: 'COMPARE PLACES', finder: 'PICK A DATE', assumptions: 'DATA & SCIENCE', export: 'SAVED RESULTS' };
    $('breadcrumbCurrent').textContent = names[name] || name.toUpperCase();
    document.title = `${names[name] || 'Luna Atlas'} · Luna Atlas Mission Planner`;
    if (name === 'assumptions') renderAssumptions();
    if (name === 'export') renderExport();
  }

  async function refreshHealth() {
    const title = $('connectionTitle');
    const detail = $('connectionDetail');
    const dot = $('statusDot');
    const sideDot = $('sidebarStatusDot');
    title.textContent = 'Checking system';
    detail.textContent = 'Reading local manifests…';
    dot.classList.remove('error');
    try {
      state.health = await fetchJSON('/api/health');
      const h = state.health;
      const ready = h.flat_horizon_analysis_ready;
      title.textContent = ready ? 'Geometry configured' : 'Configuration required';
      detail.textContent = ready
        ? `SPICE kernels verified · ${h.official_site_count} official sites`
        : `${h.kernel_count_verified || 0} kernels verified · ${h.official_site_count || 0} official sites`;
      dot.classList.toggle('ready', Boolean(ready));
      dot.classList.toggle('error', !ready);
      if (sideDot) { sideDot.classList.toggle('ready', Boolean(ready)); sideDot.classList.toggle('error', !ready); }
      $('geometryStatus').textContent = ready ? 'READY' : 'NOT CONFIGURED';
      $('frameLabel').textContent = `MOON_ME · ${h.kernel_manifest_state || 'manifest unknown'}`;
      $('mapSourceTag').textContent = h.official_site_count ? 'OFFICIAL CANDIDATES' : 'LITERATURE REFERENCES';
      $('footerCommit').textContent = h.kernel_manifest_sha256 ? `KERNEL MANIFEST ${h.kernel_manifest_sha256.slice(0, 12)}` : 'DATA PROVENANCE REQUIRED';
      renderPolarMap();
      $('previewBanner').classList.toggle('is-hidden', !state.preview);
      renderReleaseGates();
      renderAssumptions();
    } catch (error) {
      title.textContent = 'API unavailable';
      detail.textContent = error.message;
      dot.classList.add('error');
      if (sideDot) sideDot.classList.add('error');
      $('geometryStatus').textContent = 'API OFFLINE';
    }
  }

  async function loadSites() {
    const [official, references, coverage] = await Promise.all([
      fetchJSON('/api/sites'), fetchJSON('/api/reference-sites'), fetchJSON('/api/terrain-coverage')
    ]);
    state.officialSites = official.sites || [];
    state.referenceSites = references.sites || [];
    state.terrainCoverage = coverage.assets || [];
    renderSiteSelector();
    renderPolarMap();
    renderHorizonSiteSelect();
    $('mapSourceTag').textContent = state.officialSites.length ? 'OFFICIAL CANDIDATES' : 'LITERATURE REFERENCES';
  }

  function renderSiteSelector() {
    const container = $('siteSelector');
    const sites = allAvailableSites();
    if (!sites.length) {
      container.innerHTML = '<div class="empty-inline">No sites are loaded. Import the official catalogue after its release.</div>';
      return;
    }
    const kindLabel = state.officialSites.length ? 'OFFICIAL' : 'REFERENCE ONLY';
    const previouslyChecked = selectedSites();
    const defaultIds = previouslyChecked.length ? previouslyChecked : sites.slice(0, Math.min(2, sites.length)).map((s) => s.site_id);
    container.innerHTML = sites.map((site) => {
      const checked = defaultIds.includes(site.site_id);
      const label = site.terrain_status === 'verified' ? 'TERRAIN VERIFIED' : 'NO VERIFIED DEM';
      return `<label class="site-option ${checked ? 'checked' : ''}">
        <input type="checkbox" name="siteChoice" value="${esc(site.site_id)}" ${checked ? 'checked' : ''}>
        <span class="site-option-main"><b>${esc(site.name)}</b><small>${fmt(site.latitude_deg, 3)}° · ${fmt(site.longitude_deg, 3)}° E</small></span>
        <span class="site-option-tag">${state.officialSites.length ? label : kindLabel}</span>
      </label>`;
    }).join('');
    container.querySelectorAll('input[name="siteChoice"]').forEach((input) => input.addEventListener('change', () => {
      const checked = selectedSites();
      if (checked.length > 4) {
        input.checked = false;
        toast('Select at most four sites per run.', 'warn');
      }
      if (selectedSites().length > 0) {
        state.selectedSiteId = selectedSites()[0];
        renderPolarMap();
        renderHorizonSiteSelect();
      }
      updateSelectedCount();
    }));
    if (!state.selectedSiteId || !sites.some((s) => s.site_id === state.selectedSiteId)) state.selectedSiteId = defaultIds[0] || sites[0].site_id;
    updateSelectedCount();
  }

  function updateSelectedCount() {
    const count = selectedSites().length;
    $('mapSelectedCount').textContent = `${count} site${count === 1 ? '' : 's'} selected`;
  }

  function renderHorizonSiteSelect() {
    const select = $('horizonSite');
    const sites = state.currentRun?.sites?.map((result) => result.site) || allAvailableSites();
    const chosen = sites.some((s) => s.site_id === state.selectedSiteId) ? state.selectedSiteId : sites[0]?.site_id;
    select.innerHTML = sites.map((site) => `<option value="${esc(site.site_id)}" ${site.site_id === chosen ? 'selected' : ''}>${esc(site.name)}</option>`).join('');
    if (!sites.length) select.innerHTML = '<option value="">No sites</option>';
  }

  function polarPoint(site) {
    // Schematic south-polar stereographic projection. Map provides orientation only, not hazards.
    const rho = 148 * Math.tan((90 + Math.max(-89.999, Math.min(-60, Number(site.latitude_deg)))) * Math.PI / 360)
      / Math.tan(15 * Math.PI / 180);
    const angle = (Number(site.longitude_deg) || 0) * Math.PI / 180;
    return { x: 228 + rho * Math.sin(angle), y: 177 - rho * Math.cos(angle) };
  }

  function renderPolarMap() {
    const sites = allAvailableSites();
    const footprintAssets = state.terrainCoverage.filter((asset) =>
      Array.isArray(asset.footprint) && asset.footprint.length >= 3
    );
    const coverageGroup = $('mapCoverage');
    if (coverageGroup) {
      coverageGroup.innerHTML = footprintAssets.map((asset) => {
        const points = asset.footprint.map((coordinate) => polarPoint(coordinate))
          .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
        if (points.length < 3) return '';
        const pointString = points.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ');
        const stateClass = asset.footprint_status === 'verified' ? 'verified' : 'provisional';
        const resolution = `${fmt(asset.native_resolution_m, 1)} m/px`;
        return `<polygon class="dem-footprint ${stateClass}" points="${pointString}" tabindex="0" role="img" aria-label="${esc(asset.product_id)} raster footprint; ${stateClass}" data-asset-id="${esc(asset.asset_id)}"><title>${esc(asset.product_id)} · ${resolution} · ${stateClass === 'verified' ? 'reviewed coverage contract' : 'provisional extent only'}</title></polygon>`;
      }).join('');
    }
    const reviewed = footprintAssets.filter((asset) => asset.footprint_status === 'verified').length;
    const provisional = footprintAssets.length - reviewed;
    const caption = $('mapCoverageCaption');
    if (caption) {
      if (!footprintAssets.length) {
        caption.textContent = 'No local DEM footprints loaded. This is a schematic context view; it is not a terrain or hazard map.';
      } else {
        const parts = [];
        if (reviewed) parts.push(`${reviewed} reviewed footprint${reviewed === 1 ? '' : 's'}`);
        if (provisional) parts.push(`${provisional} provisional extent${provisional === 1 ? '' : 's'}`);
        caption.textContent = `${parts.join(' · ')}. Raster extents are not landing-safety zones; unreviewed outlines do not unlock terrain analysis.`;
      }
    }
    if ($('mapSourceTag')) {
      $('mapSourceTag').textContent = `${state.officialSites.length ? 'OFFICIAL CANDIDATES' : 'LITERATURE REFERENCES'}${footprintAssets.length ? ` · ${footprintAssets.length} DEM FOOTPRINTS` : ''}`;
    }
    const selected = new Set(selectedSites());
    // Near-pole sites legitimately cluster around the pole. Keep their map coordinates truthful,
    // but route selected labels to left/right rails so labels do not collide or imply false spacing.
    const visible = sites.map((site) => ({ site, point: polarPoint(site) })).filter(({ point }) =>
      Number.isFinite(point.x) && Number.isFinite(point.y) && point.x >= 72 && point.x <= 384 && point.y >= 20 && point.y <= 330
    );
    const selectedVisible = visible.filter(({ site }) => selected.has(site.site_id));
    const railIndex = { left: 0, right: 0 };
    const labelPlacement = new Map();
    selectedVisible.forEach(({ site, point }) => {
      const side = point.x < 228 ? 'left' : 'right';
      const lane = railIndex[side]++;
      labelPlacement.set(site.site_id, {
        side,
        x: side === 'left' ? 42 : 290,
        y: 54 + lane * 30,
        anchor: 'start',
        point,
      });
    });
    $('mapPoints').innerHTML = visible.map(({ site, point }) => {
      const isSelected = selected.has(site.site_id);
      const label = esc(site.name.length > 20 ? `${site.name.slice(0, 19)}…` : site.name);
      const placement = labelPlacement.get(site.site_id);
      const leader = placement
        ? `<path class="map-leader" d="M ${point.x} ${point.y} L ${placement.x - 5} ${placement.y - 3}"/>`
        : '';
      const text = placement
        ? `<text x="${placement.x}" y="${placement.y}" class="map-point-label">${label}</text>`
        : '';
      return `<g class="map-point ${isSelected ? 'selected' : ''}" tabindex="0" role="button" aria-label="Select ${esc(site.name)}" data-site-id="${esc(site.site_id)}"><title>${esc(site.name)} · ${fmt(site.latitude_deg, 4)}°, ${fmt(site.longitude_deg, 4)}° E</title>${leader}<circle class="point-ring" cx="${point.x}" cy="${point.y}" r="${isSelected ? 7 : 4.5}"/><circle class="point-core" cx="${point.x}" cy="${point.y}" r="${isSelected ? 3.4 : 2.3}"/>${text}</g>`;
    }).join('');
    $('mapPoints').querySelectorAll('[data-site-id]').forEach((node) => {
      const selectSite = () => {
        const id = node.dataset.siteId;
        const input = document.querySelector(`input[name="siteChoice"][value="${CSS.escape(id)}"]`);
        if (input && !input.checked) {
          if (selectedSites().length >= 4) {
            toast('Select at most four sites per run.', 'warn');
            return;
          }
          input.checked = true;
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        state.selectedSiteId = id;
        renderPolarMap(); renderHorizonSiteSelect(); renderHorizonChart();
      };
      node.addEventListener('click', selectSite);
      node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectSite(); } });
    });
  }

  function chartScaffold(width, height, xTitle, yTitle, xTicks, yTicks) {
    const left = 55, right = width - 18, top = 18, bottom = height - 36;
    const xGrid = xTicks.map((tick) => {
      const x = left + (right - left) * tick.position;
      return `<line x1="${x}" y1="${top}" x2="${x}" y2="${bottom}" class="grid-line"/><text x="${x}" y="${bottom + 18}" text-anchor="middle" class="axis-tick">${esc(tick.label)}</text>`;
    }).join('');
    const yGrid = yTicks.map((tick) => {
      const y = bottom - (bottom - top) * tick.position;
      return `<line x1="${left}" y1="${y}" x2="${right}" y2="${y}" class="grid-line"/><text x="${left - 9}" y="${y + 4}" text-anchor="end" class="axis-tick">${esc(tick.label)}</text>`;
    }).join('');
    return { left, right, top, bottom, svg: `${xGrid}${yGrid}<text x="${(left + right) / 2}" y="${height - 4}" text-anchor="middle" class="axis-title">${esc(xTitle)}</text><text x="12" y="${(top + bottom) / 2}" transform="rotate(-90 12 ${(top + bottom) / 2})" text-anchor="middle" class="axis-title">${esc(yTitle)}</text>` };
  }

  function renderHorizonChart() {
    const result = selectedAnalysisSite();
    const svg = $('horizonChart');
    if (!result) {
      svg.innerHTML = '<text x="360" y="150" text-anchor="middle" class="axis-title">Run an analysis or load the clearly labelled UX preview.</text>';
      return;
    }
    const width = 720, height = 300;
    const grid = chartScaffold(width, height, 'Azimuth (degrees clockwise from north)', 'Elevation (deg)',
      [{ label: '0° N', position: 0 }, { label: '90° E', position: .25 }, { label: '180° S', position: .5 }, { label: '270° W', position: .75 }, { label: '360°', position: 1 }],
      [{ label: '-10°', position: 0 }, { label: '0°', position: .25 }, { label: '10°', position: .5 }, { label: '20°', position: .75 }, { label: '30°', position: 1 }]);
    const yMin = -10, yMax = 30;
    const X = (az) => grid.left + (grid.right - grid.left) * (az / 360);
    const Y = (el) => grid.bottom - (grid.bottom - grid.top) * ((el - yMin) / (yMax - yMin));
    const horizon = Array.isArray(result.horizon_profile) ? result.horizon_profile : [];
    const earthHorizon = Array.isArray(result.earth_horizon_profile) ? result.earth_horizon_profile : [];
    const profilePath = (profile) => profile.filter((p) => Number.isFinite(p.azimuth_deg) && Number.isFinite(p.elevation_deg))
      .map((p, idx) => `${idx ? 'L' : 'M'}${X(p.azimuth_deg).toFixed(2)},${Y(p.elevation_deg).toFixed(2)}`).join(' ');
    const horizonPath = profilePath(horizon);
    const earthHorizonPath = profilePath(earthHorizon);
    const series = result.series || [];
    const chosen = series.filter((_, index) => index % Math.max(1, Math.floor(series.length / 180)) === 0);
    const pathFor = (azKey, elKey) => chosen.map((p, idx) => `${idx ? 'L' : 'M'}${X(Number(p[azKey])).toFixed(2)},${Y(Number(p[elKey])).toFixed(2)}`).join(' ');
    const cursor = chosen[Math.min(chosen.length - 1, Math.floor((state.cursorIndex / Math.max(1, series.length - 1)) * Math.max(0, chosen.length - 1)))];
    const cursorMarker = cursor ? `<circle cx="${X(cursor.sun_azimuth_deg)}" cy="${Y(cursor.sun_elevation_deg)}" r="4.5" class="sun-marker"/><circle cx="${X(cursor.earth_azimuth_deg)}" cy="${Y(cursor.earth_elevation_deg)}" r="4.5" class="earth-marker"/>` : '';
    const terrainLabel = result.terrain_status === 'terrain-verified' ? 'DEM horizon' : (result.terrain_status === 'flat' ? 'Flat spherical horizon' : 'Horizon unavailable');
    svg.innerHTML = `${grid.svg}${horizonPath ? `<path d="${horizonPath}" class="horizon-path"/>` : `<line x1="${grid.left}" y1="${Y(0)}" x2="${grid.right}" y2="${Y(0)}" class="horizon-path"/>`}
      ${earthHorizonPath && earthHorizonPath !== horizonPath ? `<path d="${earthHorizonPath}" class="earth-horizon-path"/>` : ''}
      <path d="${pathFor('sun_azimuth_deg', 'sun_elevation_deg')}" class="sun-track"/><path d="${pathFor('earth_azimuth_deg', 'earth_elevation_deg')}" class="earth-track"/>${cursorMarker}
      <text x="${grid.right - 2}" y="${grid.top + 11}" text-anchor="end" class="chart-note">${esc(terrainLabel)} · ${series.length} samples</text>`;
    $('cursorReadout').textContent = cursor ? `${cursor.utc} · Sun ${fmt(cursor.sun_elevation_deg, 2)}° elev / ${fmt(cursor.sun_margin_deg, 2)}° margin · Earth ${fmt(cursor.earth_elevation_deg, 2)}° elev / ${fmt(cursor.earth_margin_deg, 2)}° margin` : 'No sample at current cursor.';
  }

  function renderTimeline() {
    const results = currentAnalysisSites();
    const container = $('timelineChart');
    if (!results.length) {
      container.innerHTML = '<div class="empty-chart">Run an analysis or load the labelled UX preview to populate the timeline.</div>';
      $('timeStartLabel').textContent = 'START'; $('timeEndLabel').textContent = 'END'; $('cursorTime').textContent = '—';
      return;
    }
    const seriesLen = results[0].series.length;
    if (!seriesLen) { container.innerHTML = '<div class="empty-chart">No timeline samples returned.</div>'; return; }
    const tracks = results.map((result) => {
      const segments = (key, cls) => {
        const series = result.series;
        const runs = [];
        let current = Boolean(series[0][key]), begin = 0;
        for (let i = 1; i <= series.length; i += 1) {
          const next = i < series.length ? Boolean(series[i][key]) : !current;
          if (next !== current) {
            runs.push({ begin, end: i, value: current }); begin = i; current = next;
          }
        }
        return runs.filter((item) => item.value).map((item) => `<span class="track-segment ${cls}" style="left:${item.begin / series.length * 100}%;width:${(item.end - item.begin) / series.length * 100}%" title="Visible from ${esc(series[item.begin]?.utc || '')}"></span>`).join('');
      };
      return `<div class="timeline-site-row"><div class="timeline-site-name">${esc(result.site.name)}<small>${esc(result.terrain_status || 'status unknown')}</small></div><div class="timeline-tracks"><div class="track-bg">${segments('sun_visible_upper_limb', '')}</div><div class="track-bg">${segments('earth_center_clear', 'earth')}</div></div></div>`;
    }).join('');
    const cursor = results[0].series[Math.min(seriesLen - 1, state.cursorIndex)];
    container.innerHTML = tracks;
    $('timeCursor').max = String(Math.max(0, seriesLen - 1));
    $('timeCursor').value = String(Math.min(seriesLen - 1, state.cursorIndex));
    $('timeStartLabel').textContent = results[0].series[0].utc;
    $('timeEndLabel').textContent = results[0].series[seriesLen - 1].utc;
    $('cursorTime').textContent = cursor?.utc || '—';
    $('timelineRangeLabel').textContent = `${results[0].series[0].utc} → ${results[0].series[seriesLen - 1].utc}`;
    container.querySelectorAll('.track-bg').forEach((track) => {
      const marker = document.createElement('span');
      marker.className = 'timeline-cursor';
      marker.style.left = `${state.cursorIndex / Math.max(1, seriesLen - 1) * 100}%`;
      track.appendChild(marker);
    });
  }

  function renderMetricCards() {
    const results = currentAnalysisSites();
    const container = $('metricsGrid');
    $('metricsStatus').textContent = state.preview ? 'UX PREVIEW ONLY' : (state.currentAnalysis ? 'FROM COMPUTED RUN' : 'NO COMPUTED RUN');
    if (!results.length) {
      container.innerHTML = '<div class="empty-card"><span class="empty-card-icon">∿</span><b>No computed metrics</b><span>Results appear here after an analysis or a labelled UX preview.</span></div>';
      return;
    }
    container.innerHTML = results.map((result) => {
      const m = result.metrics || {};
      const status = result.terrain_status === 'terrain-verified' ? 'verified' : result.terrain_status === 'flat' ? 'flat' : 'preview';
      const statusText = result.terrain_status === 'terrain-verified' ? 'TERRAIN VERIFIED' : result.terrain_status === 'flat' ? 'FLAT HORIZON' : 'INCOMPLETE / PREVIEW';
      return `<article class="metric-card"><div class="metric-card-head"><div><div class="metric-site">${esc(result.site.name)}</div><small class="metric-source">${esc(result.site.origin || 'unknown source')} · ${esc(result.site.site_id)}</small></div><span class="status-tag ${status}">${statusText}</span></div>
        <div class="metric-primary">${fmtPercent(m.sunlit_fraction)} <small>sunlit</small></div><div class="metric-divider"></div>
        <div class="metric-pair"><div class="metric-mini"><b>${fmtPercent(m.dte_clear_fraction)}</b><span>Earth centre clear</span></div><div class="metric-mini"><b>${fmtHours(m.longest_darkness)}</b><span>Longest darkness</span></div><div class="metric-mini"><b>${fmtHours(m.longest_dte_gap)}</b><span>Longest Earth gap</span></div><div class="metric-mini"><b>${fmtHours(m.longest_joint_outage)}</b><span>Longest joint outage</span></div></div>
        <div class="metric-divider"></div><div class="metric-source">${fmt(m.sun_window_count ?? m.window_count, 0)} Sun windows · median ${fmtHours({duration_s: m.median_sun_window_s ?? m.median_window_duration_s})}</div></article>`;
    }).join('');
  }

  function renderCompare() {
    renderHorizonSiteSelect();
    renderPolarMap();
    renderHorizonChart();
    renderTimeline();
    renderMetricCards();
    renderExport();
  }

  function renderAssumptions() {
    if (!state.health) return;
    const h = state.health;
    const strip = $('validationStrip');
    const ready = h.flat_horizon_analysis_ready;
    strip.innerHTML = `<div class="status-strip-icon">${ready ? '✓' : '!'}</div><div><b>${ready ? 'Geometry configuration preflight passed' : 'Scientific analysis is configuration-blocked'}</b><span>SPICEyPy: ${h.spiceypy_installed ? 'installed' : 'not installed'} · hash-verified kernels: ${h.kernel_count_verified || 0} · official sites: ${h.official_site_count || 0} · registered DEMs: ${h.dem_asset_count || 0}. Configuration alone does not establish Horizons agreement.</span></div>`;
    const setupMessage = $('bootstrapMessage');
    if (setupMessage) {
      const missing = [];
      if (!h.spiceypy_installed) missing.push('install SpiceyPy/runtime dependencies');
      if (!h.kernel_preflight_ready) missing.push('fetch and preflight NAIF kernels');
      if (!(h.dem_asset_count > 0)) missing.push('stage public PGDA reference DEMs');
      if (!(h.official_site_count > 0)) missing.push('import the official challenge site catalogue after release');
      setupMessage.textContent = missing.length
        ? `Current blockers: ${missing.join('; ')}. Downloaded DEMs remain disabled for terrain calculations until CRS/frame and vertical-datum reviews are recorded.`
        : 'Inputs are present. Next: verify the DEM datum contract and complete the predeclared JPL Horizons geometry comparison before making scientific claims.';
      setupMessage.className = 'form-message visible warning';
    }
    const cards = [
      ['Time system', 'Inputs are explicit UTC; conversion to SPICE ET/TDB happens before geometry and root refinement. UTC is not numerically substituted for ET.'],
      ['Reference frame', 'The implementation requests MOON_ME with LT+S corrections. The associated kernel set and reference-ephemeris chain must be verified against JPL Horizons.'],
      ['Sun visibility', 'Sun upper limb is visible when elevation + apparent solar semidiameter − local horizon elevation > 0.'],
      ['Earth visibility', 'Primary flag means Earth centre geometrically clears the local horizon plus the configured clearance. It is not a communications link guarantee.'],
      ['Terrain uncertainty', 'DEM pixel spacing is not DEM accuracy. Incomplete ray coverage is not silently treated as open sky.'],
      ['Event precision', 'Brent roots are refined inside detected brackets. The current algorithm reports local extrema diagnostics but does not certify that all possible events were detected.']
    ];
    $('assumptionCards').innerHTML = cards.map(([title, body]) => `<article class="assumption-card"><div class="assumption-card-top"><h3>${esc(title)}</h3><span class="math-tag">MODEL CONTRACT</span></div><p>${esc(body)}</p></article>`).join('');
    renderTerrainInventory();
    renderSourceList();
  }

  async function renderTerrainInventory() {
    const summary = $('terrainInventorySummary');
    const list = $('terrainInventory');
    const status = $('terrainInventoryStatus');
    if (!summary || !list || !status) return;
    try {
      const payload = await fetchJSON('/api/terrain-coverage');
      const assets = payload.assets || [];
      const verified = Number(payload.verified_coverage_count || 0);
      const provisional = Number(payload.provisional_coverage_count || 0);
      const unavailable = assets.filter((item) => item.footprint_status === 'unavailable').length;
      const assetCount = Number(payload.asset_count || 0);
      if (payload.manifest_state === 'invalid') status.textContent = 'MANIFEST INVALID';
      else if (!assetCount) status.textContent = 'NO ASSETS REGISTERED';
      else if (unavailable === assetCount) status.textContent = 'ALL FILES UNAVAILABLE';
      else if (verified === assetCount) status.textContent = 'ALL CONTRACTS REVIEWED';
      else status.textContent = 'REVIEW REQUIRED';
      summary.innerHTML = `<div class="inventory-stat"><span>Registered assets</span><b>${fmt(assetCount, 0)}</b></div><div class="inventory-stat"><span>Reviewed footprints</span><b class="inventory-good">${fmt(verified, 0)}</b></div><div class="inventory-stat"><span>Provisional extents</span><b class="inventory-warn">${fmt(provisional, 0)}</b></div><div class="inventory-stat"><span>Unavailable files</span><b>${fmt(unavailable, 0)}</b></div>`;
      if (!assets.length) {
        const issues = (payload.issues || []).map((issue) => `<li>${esc(issue)}</li>`).join('');
        list.innerHTML = `<div class="inventory-empty"><span class="inventory-empty-icon">⌁</span><div><b>No DEM assets registered</b><p>Run the public-input bootstrap to fetch and register candidate PGDA rasters. The manifest records each asset, but no terrain result is assumed until the raster is present and the CRS/vertical datum gates pass.</p>${issues ? `<ul>${issues}</ul>` : ''}</div></div>`;
        return;
      }
      list.innerHTML = assets.map((item) => {
        const stateLabel = item.footprint_status === 'verified' ? 'REVIEWED CONTRACT' : item.footprint_status === 'provisional' ? 'PROVISIONAL' : 'UNAVAILABLE';
        const stateClass = item.footprint_status === 'verified' ? 'inventory-pill good' : item.footprint_status === 'provisional' ? 'inventory-pill warn' : 'inventory-pill bad';
        const source = /^https?:\/\//i.test(String(item.source_url || '')) ? `<a href="${esc(item.source_url)}" target="_blank" rel="noopener noreferrer">Publisher record ↗</a>` : '<span class="inventory-muted">No source URL</span>';
        const hashValue = item.hash_verified ? 'SHA-256 match' : item.file_present ? 'Hash mismatch' : 'File missing';
        const rasterShape = item.raster_width && item.raster_height ? `${fmt(item.raster_width, 0)} × ${fmt(item.raster_height, 0)} px` : 'Raster dimensions unavailable';
        const crs = item.raster_crs ? esc(item.raster_crs) : 'Not inspected';
        const issue = item.issue ? `<p class="inventory-issue">${esc(item.issue)}</p>` : '';
        return `<article class="inventory-asset"><div class="inventory-asset-head"><div><span class="inventory-asset-id">${esc(item.asset_id)}</span><h3>${esc(item.product_id)}</h3></div><span class="${stateClass}">${stateLabel}</span></div><div class="inventory-asset-metrics"><div><span>Native resolution</span><b>${fmt(item.native_resolution_m, 1)} m/px</b></div><div><span>Declared range</span><b>${fmt(item.min_range_m / 1000, 1)}–${fmt(item.max_range_m / 1000, 1)} km</b></div><div><span>File integrity</span><b>${esc(hashValue)}</b></div><div><span>Raster dimensions</span><b>${esc(rasterShape)}</b></div></div><div class="inventory-contract"><span class="${item.crs_contract_verified ? 'contract-pass' : 'contract-open'}">CRS contract ${item.crs_contract_verified ? 'reviewed' : 'open'}</span><span class="${item.vertical_datum_verified ? 'contract-pass' : 'contract-open'}">Vertical datum ${item.vertical_datum_verified ? 'approved' : 'open'}</span></div><div class="inventory-crs"><span>Embedded CRS</span><code>${crs}</code></div><div class="inventory-asset-footer">${source}<span>${Array.isArray(item.site_ids) ? esc(item.site_ids.join(', ')) : 'No site association'}</span></div>${issue}</article>`;
      }).join('');
    } catch (error) {
      status.textContent = 'INVENTORY ERROR';
      summary.innerHTML = '<div class="inventory-stat"><span>Manifest status</span><b class="inventory-warn">Unavailable</b></div>';
      list.innerHTML = `<div class="inventory-empty"><b>Could not inspect local DEM assets</b><p>${esc(error.message)}</p></div>`;
    }
  }

  async function renderSourceList() {
    try {
      const payload = await fetchJSON('/api/sources');
      const items = payload.sources || payload.items || [];
      $('sourceList').innerHTML = items.map((item) => `<article class="source-row"><div class="source-name">${esc(item.name || item.title || item.id)}</div><div class="source-role">${esc(item.role || item.description || item.use || '')}</div><a href="${esc(item.url || item.source_url || '#')}" target="_blank" rel="noopener noreferrer">Open source ↗</a></article>`).join('') || '<div class="empty-inline">No source register entries returned.</div>';
    } catch (error) {
      $('sourceList').innerHTML = `<div class="empty-inline">Could not load source register: ${esc(error.message)}</div>`;
    }
  }

  function renderReleaseGates() {
    const h = state.health || {};
    const gates = [
      ['A · Official data contract', h.official_site_count > 0, `${h.official_site_count || 0} official sites loaded; reference points remain separate.`],
      ['B · SPICE geometry', h.flat_horizon_analysis_ready, `${h.kernel_count_verified || 0} kernels hash-verified; independent Horizons comparison remains outstanding.`],
      ['C · Terrain horizon', h.terrain_analysis_ready, `${h.dem_asset_count || 0} DEM assets present; per-site full coverage and DEM datum validation required.`],
      ['D · Events and metrics', false, 'Synthetic tests exist; complete-window detection and real epoch convergence evidence are not certified.'],
      ['E · Product integration', false, 'Run analysis and finder APIs exist; review with actual input files and user tasks remains.'],
      ['F · Release and offline', false, 'Clean install, offline rehearsal, public deployment and release evidence are not yet recorded.']
    ];
    $('releaseGates').innerHTML = gates.map(([name, pass, text], index) => `<div class="gate-row"><span class="gate-code">${String.fromCharCode(65 + index)}</span><span class="gate-name">${esc(name)}</span><span class="gate-evidence">${esc(text)}</span><span class="gate-state ${pass ? 'pass' : ''}">${pass ? 'PASS' : 'BLOCKED'}</span></div>`).join('');
  }

  async function refreshSavedRuns() {
    const select = $('savedRunSelect');
    const button = $('loadSavedRun');
    const message = $('savedRunsMessage');
    if (!select || !button || !message) return;
    const previous = select.value;
    try {
      const listing = await fetchJSON('/api/runs?limit=50');
      state.savedRuns = listing.runs || [];
      select.innerHTML = '<option value="">Select a saved run…</option>' + state.savedRuns.map((run) => {
        const sites = (run.site_names || []).join(', ') || `${run.site_count || 0} site(s)`;
        const date = String(run.created_utc || 'creation time unknown').replace('T', ' ');
        return `<option value="${esc(run.run_id)}">${esc(date)} · ${esc(run.analysis_kind)} · ${esc(sites)} · ${esc(run.validation_status)}</option>`;
      }).join('');
      if (state.savedRuns.some((run) => run.run_id === previous)) select.value = previous;
      button.disabled = state.savedRuns.length === 0 || !select.value;
      message.textContent = state.savedRuns.length
        ? `${listing.total} saved run(s) indexed. Loading an existing result does not recompute it; review the embedded provenance and validation status.`
        : 'No persisted runs found. Run a real analysis after configuring SPICE kernels; the synthetic UX preview is intentionally not saved.';
      if (listing.invalid_run_files_ignored) message.textContent += ` Ignored ${listing.invalid_run_files_ignored} malformed or inconsistent run file(s).`;
    } catch (error) {
      select.innerHTML = '<option value="">Saved-run index unavailable</option>';
      button.disabled = true;
      message.textContent = `Could not list saved runs: ${error.message}`;
    }
  }

  async function loadSavedRun() {
    const runId = $('savedRunSelect').value;
    if (!runId) return setMessage('savedRunsMessage', 'Select a saved run first.', 'warning');
    const button = $('loadSavedRun');
    button.disabled = true;
    button.textContent = 'Loading…';
    try {
      const run = await fetchJSON(`/api/runs/${encodeURIComponent(runId)}`);
      if (!['spice_backed_analysis', 'landing_window_finder'].includes(run.analysis_kind)) {
        throw new Error(`Unsupported saved run kind: ${run.analysis_kind || 'missing'}`);
      }
      state.currentRun = run;
      state.preview = false;
      $('previewBanner').classList.add('is-hidden');
      if (run.analysis_kind === 'spice_backed_analysis') {
        state.currentAnalysis = run;
        state.finderRun = null;
        const siteIds = (run.sites || []).map((item) => item.site?.site_id).filter(Boolean);
        state.selectedSiteId = siteIds[0] || null;
        state.cursorIndex = 0;
        document.querySelectorAll('input[name="siteChoice"]').forEach((input) => { input.checked = siteIds.includes(input.value); });
        renderCompare();
        showView('compare');
      } else {
        state.currentAnalysis = null;
        state.finderRun = run;
        renderFinderGrid(run);
        showView('finder');
      }
      renderExport();
      setMessage('savedRunsMessage', `Loaded ${run.run_id}. Status: ${run.validation_status}. Existing saved outputs are not recalculated.`, 'success');
      toast('Saved run loaded from local provenance store.', 'success');
    } catch (error) {
      setMessage('savedRunsMessage', `Could not load saved run: ${error.message}`, 'error');
    } finally {
      button.textContent = 'Load saved run ↗';
      button.disabled = state.savedRuns.length === 0 || !$('savedRunSelect').value;
    }
  }

  function renderExport() {
    const run = state.currentRun;
    $('runStatusTag').textContent = run ? (run.validation_status || 'COMPUTED') : 'NO RUN LOADED';
    const runIsPreview = run?.analysis_kind === 'ux_preview_not_science';
    $('downloadJSON').disabled = !run || runIsPreview;
    $('downloadCSV').disabled = !run || runIsPreview;
    if (!run || runIsPreview) {
      $('exportRunCard').className = 'empty-export';
      $('exportRunCard').innerHTML = `<div class="empty-export-icon">⇩</div><b>${state.preview ? 'Preview data is not exportable' : 'No real analysis run is available'}</b><p>${state.preview ? 'The UX preview is intentionally excluded from JSON/CSV exports so it cannot be confused with model output.' : 'Run Compare or the Landing-window finder. Export is enabled only for computed API results.'}</p><button class="secondary-button" data-jump="compare">Go to Compare</button>`;
      $('provenanceTable').innerHTML = '<div class="empty-inline">No run manifest to display.</div>';
      $('exportRunCard').querySelector('[data-jump]')?.addEventListener('click', () => showView('compare'));
      return;
    }
    $('exportRunCard').className = 'export-loaded-card';
    const sites = run.sites || run.site_results || [];
    $('exportRunCard').innerHTML = `<div class="export-run-icon">✓</div><div class="export-run-info"><b>${esc(run.analysis_kind || 'analysis')} · ${esc(run.run_id)}</b><p>${esc(run.created_utc)} · ${sites.length} site record(s) · ${esc(run.validation_status || 'status unavailable')}</p><small>${esc(run.warning || 'Review assumptions before interpreting the output.')}</small></div>`;
    const p = run.provenance || {};
    const pairs = [
      ['Run ID', run.run_id], ['Analysis kind', run.analysis_kind], ['Validation status', run.validation_status],
      ['Git commit', p.git_commit], ['Kernel manifest SHA-256', p.kernel_manifest_sha256],
      ['DEM manifest SHA-256', p.dem_manifest_sha256], ['SPICE frame', p.spice_frame],
      ['Aberration correction', p.aberration_correction], ['UTC / ET contract', p.time_contract],
    ];
    $('provenanceTable').innerHTML = pairs.map(([key, value]) => `<div class="prov-row"><span class="prov-key">${esc(key)}</span><b class="prov-value">${esc(value || '—')}</b></div>`).join('');
    $('downloadJSON').onclick = () => window.location.href = `/api/runs/${encodeURIComponent(run.run_id)}/export.json`;
    $('downloadCSV').onclick = () => window.location.href = `/api/runs/${encodeURIComponent(run.run_id)}/export.csv`;
  }

  async function runAnalysis() {
    const ids = selectedSites();
    if (!ids.length || ids.length > 4) return setMessage('analysisMessage', 'Select between one and four sites.', 'error');
    const button = $('runAnalysis'); button.disabled = true; button.dataset.original = button.textContent; button.textContent = 'Computing…';
    setMessage('analysisMessage', 'Checking kernel/data preflight and evaluating geometry…');
    try {
      const payload = {
        site_ids: ids,
        start_utc: utcValue('analysisStart'),
        end_utc: utcValue('analysisEnd'),
        coarse_step_min: Number($('coarseStep').value),
        event_tolerance_s: 1,
        sun_observer_height_m: 2,
        antenna_height_m: 2,
        earth_min_clearance_deg: Number($('earthClearance').value),
        horizon_mode: $('horizonMode').value,
      };
      const result = await fetchJSON('/api/analysis', { method: 'POST', body: JSON.stringify(payload) });
      state.currentRun = result;
      state.currentAnalysis = result;
      state.preview = false;
      state.selectedSiteId = result.sites?.[0]?.site?.site_id || ids[0];
      state.cursorIndex = 0;
      $('previewBanner').classList.add('is-hidden');
      setMessage('analysisMessage', `Analysis ${result.run_id} saved. Status: ${result.validation_status}. Review terrain labels and event limitations.`, 'success');
      renderCompare();
      await refreshSavedRuns();
      toast('Analysis completed and persisted with provenance.', 'success');
    } catch (error) {
      setMessage('analysisMessage', error.message, 'error');
      toast('Real analysis did not run; inspect the error and system preflight.', 'error');
    } finally {
      button.disabled = false; button.textContent = '▶ Run real analysis ↗';
    }
  }

  function loadPreview() {
    const sites = allAvailableSites();
    const selected = selectedSites().map((id) => sites.find((site) => site.site_id === id)).filter(Boolean);
    const chosen = (selected.length ? selected : sites.slice(0, 2)).slice(0, 4);
    if (!chosen.length) return toast('No site coordinates available for preview.', 'warn');
    const start = new Date('2027-01-01T00:00:00Z');
    const samples = 97;
    const end = new Date(start.getTime() + (samples - 1) * 6 * 3600 * 1000);
    const results = chosen.map((site, siteIndex) => {
      const series = [];
      for (let i = 0; i < samples; i += 1) {
        const phase = i / (samples - 1) * Math.PI * 2;
        const sunElevation = -2.8 + 5.6 * Math.sin(phase * 1.12 + siteIndex * .65);
        const earthElevation = 3.5 + 3.8 * Math.cos(phase * .55 + siteIndex * .9);
        series.push({
          utc: new Date(start.getTime() + i * 6 * 3600 * 1000).toISOString().replace('.000', ''),
          sun_azimuth_deg: (i * 8 + siteIndex * 37) % 360,
          sun_elevation_deg: sunElevation, sun_margin_deg: sunElevation + 0.25,
          sun_visible_upper_limb: sunElevation + .25 > 0,
          earth_azimuth_deg: (i * 3 + 72 + siteIndex * 50) % 360,
          earth_elevation_deg: earthElevation, earth_margin_deg: earthElevation - 1.2,
          earth_center_clear: earthElevation - 1.2 > 0,
        });
      }
      return {
        site: { ...site, origin: 'reference', catalogue_kind: 'preview_only' },
        terrain_status: 'flat', terrain: { mode: 'preview', terrain_status: 'flat' }, series,
        horizon_profile: Array.from({ length: 73 }, (_, i) => ({ azimuth_deg: i * 5, elevation_deg: -1.2 + .8 * Math.sin(i / 4 + siteIndex) })),
        metrics: {
          sunlit_fraction: .31 + siteIndex * .055, dte_clear_fraction: .82 - siteIndex * .045,
          longest_darkness: { duration_s: (30 + siteIndex * 8) * 3600, truncated_start: false, truncated_end: false },
          longest_dte_gap: { duration_s: (6 + siteIndex * 2.3) * 3600, truncated_start: false, truncated_end: false },
          longest_joint_outage: { duration_s: (4 + siteIndex * 1.2) * 3600, truncated_start: false, truncated_end: false },
          window_count: 5 - siteIndex, median_window_duration_s: (8 + siteIndex) * 3600,
        },
      };
    });
    state.currentRun = { run_id: null, analysis_kind: 'ux_preview_not_science', validation_status: 'preview_not_scientific_output', warning: 'SIMULATED INTERFACE DATA ONLY. Never use for mission decisions or exports.', settings: { start_utc: start.toISOString(), end_utc: end.toISOString(), horizon_mode: 'preview' }, sites: results, provenance: {} };
    state.currentAnalysis = state.currentRun;
    state.preview = true;
    state.selectedSiteId = results[0].site.site_id;
    state.cursorIndex = 14;
    $('previewBanner').classList.remove('is-hidden');
    $('analysisMessage').textContent = 'UX preview loaded. All numbers are invented UI fixtures; run real analysis to replace them. Preview exports are disabled.';
    renderCompare();
    toast('Labelled UX preview loaded. These are not physical predictions.', 'warn');
  }

  function renderFinderPreview() {
    const sites = selectedSites().map((id) => siteById(id)).filter(Boolean);
    const start = $('finderStart').value || '2027-01-01';
    const end = $('finderEnd').value || '2027-01-20';
    const startDate = new Date(`${start}T00:00:00Z`), endDate = new Date(`${end}T00:00:00Z`);
    const step = Math.max(1, Number($('candidateStep').value) || 1);
    const dates = [];
    for (let time = startDate.getTime(); time <= endDate.getTime() && dates.length < 90; time += step * 86400000) dates.push(new Date(time).toISOString().slice(0, 10));
    const selected = sites.length ? sites : allAvailableSites().slice(0, 2);
    const cells = [];
    selected.forEach((site, si) => dates.forEach((date, di) => {
      const feasible = ((di + si * 2) % 7) > 1 && ((di * 2 + si) % 11) !== 0;
      cells.push({ site_id: site.site_id, start_utc: `${date}T00:00:00Z`, end_utc: `${date}T00:00:00Z`, feasible, first_failed_constraint: feasible ? null : (di % 2 ? 'max_darkness' : 'max_dte_gap'), failures: feasible ? [] : [{ constraint: di % 2 ? 'max_darkness' : 'max_dte_gap', actual: 68 + di % 5, limit: 50, violation: 18 + di % 5, unit: 'h' }], metrics: {} });
    }));
    state.finderRun = { analysis_kind: 'ux_preview_not_science', validation_status: 'preview_not_scientific_output', warning: 'Synthetic UI fixture; not a lunar result.', grid: cells, candidate_dates: dates, site_ids: selected.map((s) => s.site_id) };
    renderFinderGrid(state.finderRun);
    setMessage('finderMessage', 'UX preview grid loaded. Cell states are illustrative and must not be interpreted as viable mission dates.', 'warning');
  }

  async function runFinder() {
    const ids = selectedSites();
    if (!ids.length) return setMessage('finderMessage', 'Select at least one site on Compare.', 'error');
    const button = $('runFinder'); button.disabled = true; button.textContent = 'Evaluating…';
    setMessage('finderMessage', 'Generating one window set over the search range + mission duration…');
    try {
      const payload = {
        site_ids: ids,
        search_start_utc: dateUtc('finderStart'),
        search_end_utc: dateUtc('finderEnd'),
        candidate_step_days: Number($('candidateStep').value),
        mission_duration_days: Number($('missionDuration').value),
        constraints: {
          max_darkness_h: Number($('maxDarkness').value),
          max_dte_gap_h: Number($('maxEarthGap').value),
          max_joint_outage_h: Number($('maxJointGap').value),
          min_sunlit_fraction: Number($('minSunlit').value),
        },
        coarse_step_min: Number($('coarseStep').value), event_tolerance_s: 1,
        sun_observer_height_m: 2, antenna_height_m: 2,
        earth_min_clearance_deg: Number($('earthClearance').value), horizon_mode: $('horizonMode').value,
      };
      const result = await fetchJSON('/api/finder', { method: 'POST', body: JSON.stringify(payload) });
      state.finderRun = result;
      state.currentRun = result;
      state.preview = false;
      $('previewBanner').classList.add('is-hidden');
      renderFinderGrid(result);
      renderExport();
      await refreshSavedRuns();
      setMessage('finderMessage', `Finder ${result.run_id} completed. Results are computed; validation status: ${result.validation_status}.`, 'success');
      toast('Landing-window search completed.', 'success');
    } catch (error) {
      setMessage('finderMessage', error.message, 'error');
    } finally {
      button.disabled = false; button.textContent = '⌕ Evaluate dates ↗';
    }
  }

  function renderFinderGrid(run) {
    const grid = run.grid || [];
    const selectedIds = [...new Set(grid.map((cell) => cell.site_id))];
    const dates = run.candidate_dates || [...new Set(grid.map((cell) => cell.start_utc))];
    const sites = selectedIds.map((id) => siteById(id) || { site_id: id, name: id });
    const lookup = new Map(grid.map((cell) => [`${cell.site_id}|${cell.start_utc}`, cell]));
    if (!dates.length || !sites.length) {
      $('finderGrid').innerHTML = '<div class="empty-chart">No candidate cells returned.</div>';
      $('finderSummary').textContent = 'No results'; return;
    }
    $('finderSummary').innerHTML = `<span class="summary-chip success"><b>${grid.filter((cell) => cell.feasible).length}</b> / ${grid.length} combinations pass</span><span class="summary-chip"><b>${dates.length}</b> candidate dates · ${sites.length} sites</span><span class="summary-chip">${esc(run.validation_status || 'computed')}</span>`;
    const header = `<thead><tr><th>Site / start date</th>${dates.map((date) => `<th>${esc(String(date).slice(0, 10))}</th>`).join('')}</tr></thead>`;
    const body = sites.map((site) => `<tr><th class="row-label">${esc(site.name)}</th>${dates.map((date) => {
      const keyDate = typeof date === 'string' ? date : date.start_utc;
      const cell = lookup.get(`${site.site_id}|${keyDate}`) || lookup.get(`${site.site_id}|${keyDate}T00:00:00Z`);
      if (!cell) return '<td><span class="finder-cell unknown" title="No cell data">—</span></td>';
      return `<td><button class="grid-cell ${cell.feasible ? 'pass' : 'fail'}" data-site-id="${esc(cell.site_id)}" data-start="${esc(cell.start_utc)}" title="${cell.feasible ? 'All active constraints pass' : `Fails ${esc(cell.first_failed_constraint || 'one or more constraints')}`}">${cell.feasible ? 'PASS' : 'FAIL'}</button></td>`;
    }).join('')}</tr>`).join('');
    $('finderGrid').innerHTML = `<table class="feasibility-table">${header}<tbody>${body}</tbody></table>`;
    $('finderGrid').querySelectorAll('button[data-site-id]').forEach((button) => button.addEventListener('click', () => {
      const cell = grid.find((item) => item.site_id === button.dataset.siteId && item.start_utc === button.dataset.start);
      renderFailureDetail(cell, run);
    }));
    renderFailureDetail(grid[0], run);
  }

  function renderFailureDetail(cell, run) {
    if (!cell) return;
    const site = siteById(cell.site_id);
    const failures = cell.failures || [];
    $('failureDetail').innerHTML = `<div class="failure-card"><h3>${esc(site?.name || cell.site_id)} · ${esc(String(cell.start_utc).slice(0, 10))} · <span class="${cell.feasible ? 'failure-pass' : 'failure-no'}">${cell.feasible ? 'ALL CONSTRAINTS PASS' : 'CONSTRAINT FAILURE'}</span></h3>
      ${cell.feasible ? '<p>Every enabled geometric constraint passes for this configured mission duration. This does not certify landing safety or communications availability.</p>' : `<div class="failure-lines">${failures.map((f) => `<div class="failure-line"><b>${esc(f.constraint)}</b><span>Actual ${fmt(f.unit === 's' ? f.actual / 3600 : f.actual, 3)} ${esc(f.unit === 's' ? 'h' : f.unit)} · limit ${fmt(f.unit === 's' ? f.limit / 3600 : f.limit, 3)}</span><b class="violation">+${fmt(f.unit === 's' ? f.violation / 3600 : f.violation, 3)} ${esc(f.unit === 's' ? 'h' : f.unit)}</b></div>`).join('') || `<p>First failed constraint: ${esc(cell.first_failed_constraint || 'unknown')}.</p>`}</div>`}
      <button class="secondary-button" id="inspectFinderCell">Inspect mission interval in Compare ↗</button></div>`;
    $('inspectFinderCell').addEventListener('click', async () => {
      if (run.validation_status === 'preview_not_scientific_output') {
        setMessage('analysisMessage', 'This preview cell is synthetic; no mission interval will be treated as a computed result.', 'warning');
        showView('compare'); return;
      }
      const date = new Date(cell.start_utc);
      const end = new Date(cell.end_utc);
      $('analysisStart').value = utcToLocalInput(cell.start_utc);
      $('analysisEnd').value = utcToLocalInput(cell.end_utc);
      const checkbox = document.querySelector(`input[name="siteChoice"][value="${CSS.escape(cell.site_id)}"]`);
      document.querySelectorAll('input[name="siteChoice"]').forEach((el) => { el.checked = el.value === cell.site_id; });
      if (checkbox) checkbox.checked = true;
      state.selectedSiteId = cell.site_id;
      showView('compare'); renderPolarMap(); renderHorizonSiteSelect(); await runAnalysis();
    });
  }

  function bindEvents() {
    document.querySelectorAll('.nav-item[data-view]').forEach((button) => button.addEventListener('click', () => showView(button.dataset.view)));
    document.querySelectorAll('[data-jump="compare"]').forEach((button) => button.addEventListener('click', () => showView('compare')));
    $('refreshHealth').addEventListener('click', refreshHealth);
    $('copyBootstrapCommand').addEventListener('click', async () => {
      const command = $('bootstrapCommand').textContent.trim();
      try {
        await navigator.clipboard.writeText(command);
        setMessage('bootstrapMessage', `Copied: ${command}`, 'success');
      } catch (_error) {
        setMessage('bootstrapMessage', `Clipboard unavailable. Copy this command manually: ${command}`, 'warning');
      }
    });
    $('runAnalysis').addEventListener('click', runAnalysis);
    $('loadPreview').addEventListener('click', loadPreview);
    $('togglePreview').addEventListener('click', () => { state.preview = false; $('previewBanner').classList.add('is-hidden'); if (state.currentRun?.analysis_kind === 'ux_preview_not_science') { state.currentRun = null; state.currentAnalysis = null; renderCompare(); renderExport(); } });
    $('finderPreview').addEventListener('click', renderFinderPreview);
    $('runFinder').addEventListener('click', runFinder);
    $('refreshSavedRuns').addEventListener('click', refreshSavedRuns);
    $('savedRunSelect').addEventListener('change', () => { $('loadSavedRun').disabled = !$('savedRunSelect').value; });
    $('loadSavedRun').addEventListener('click', loadSavedRun);
    $('horizonSite').addEventListener('change', () => { state.selectedSiteId = $('horizonSite').value; renderHorizonChart(); });
    $('timeCursor').addEventListener('input', () => {
      state.cursorIndex = Number($('timeCursor').value);
      renderTimeline(); renderHorizonChart();
    });
    $('horizonMode').addEventListener('change', () => {
      if ($('horizonMode').value === 'terrain' && !state.health?.terrain_analysis_ready) {
        setMessage('analysisMessage', 'Terrain mode selected, but DEM assets are not fully configured. The API will refuse to return unverified terrain metrics.', 'warning');
      }
    });
    document.querySelectorAll('[data-view]').forEach((item) => item.addEventListener('keydown', (event) => { if (event.key === 'Enter') showView(item.dataset.view); }));
  }

  function tickClock() {
    $('utcClock').textContent = new Date().toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC');
  }

  async function init() {
    bindEvents(); tickClock(); window.setInterval(tickClock, 1000);
    // Defaults represent exact UTC midnights even when the browser runs in another time zone.
    $('analysisStart').value = utcToLocalInput('2027-01-01T00:00:00Z');
    $('analysisEnd').value = utcToLocalInput('2027-01-31T00:00:00Z');
    $('finderStart').value = '2027-01-01'; $('finderEnd').value = '2027-03-31';
    $('previewBanner').classList.add('is-hidden');
    try { await loadSites(); } catch (error) { $('siteSelector').innerHTML = `<div class="empty-inline">Catalogue load failed: ${esc(error.message)}</div>`; }
    await refreshHealth();
    await refreshSavedRuns();
    renderCompare();
    renderAssumptions(); renderReleaseGates();
    // Start in the same labelled, populated UX-preview state shown in the design preview.
    // This uses synthetic display fixtures only; a real analysis replaces it when configured.
    loadPreview();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
