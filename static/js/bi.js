/* Pustaka kecil: format angka, grafik (Chart.js), network graph, heatmap */
const PAL = ['#0e7c86', '#3b6fd4', '#e8a317', '#d9453d', '#8e5bd0', '#0f9d78', '#64748b', '#be185d', '#0891b2', '#65a30d'];
const fmt = {
  num: (x, d = 0) => (x == null ? '-' : Number(x).toLocaleString('id-ID', { minimumFractionDigits: d, maximumFractionDigits: d })),
  rp: x => 'Rp ' + Number(x).toLocaleString('id-ID', { maximumFractionDigits: 0 }),
  rps: x => x >= 1e9 ? 'Rp ' + (x / 1e9).toLocaleString('id-ID', { maximumFractionDigits: 2 }) + ' M'
    : x >= 1e6 ? 'Rp ' + (x / 1e6).toLocaleString('id-ID', { maximumFractionDigits: 1 }) + ' jt'
    : x >= 1e3 ? 'Rp ' + (x / 1e3).toLocaleString('id-ID', { maximumFractionDigits: 0 }) + ' rb' : 'Rp ' + Math.round(x),
  pct: (x, d = 1) => (x * 100).toLocaleString('id-ID', { minimumFractionDigits: d, maximumFractionDigits: d }) + '%',
};
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

if (window.Chart) {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = '#5b6882';
  Chart.defaults.borderColor = '#e9edf3';
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.tooltip.backgroundColor = '#0d1828';
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.maintainAspectRatio = false;
}
const CH = {};
function mk(id, cfg) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (CH[id]) CH[id].destroy();
  CH[id] = new Chart(el, cfg);
  return CH[id];
}

/* --- grafik siap pakai --- */
function barChart(id, labels, values, o = {}) {
  return mk(id, {
    type: 'bar',
    data: { labels, datasets: [{ data: values, backgroundColor: o.colors || o.color || PAL[0], borderRadius: 5, maxBarThickness: o.thick || 34 }] },
    options: {
      indexAxis: o.horizontal ? 'y' : 'x',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ' ' + (o.fmt || fmt.num)(c.parsed[o.horizontal ? 'x' : 'y']) } } },
      scales: {
        x: { grid: { display: !!o.horizontal }, ticks: Object.assign({ maxRotation: 50, autoSkip: false }, o.horizontal ? { callback: v => (o.axfmt || o.fmt || fmt.num)(v) } : {}) },
        y: { grid: { display: !o.horizontal }, beginAtZero: true, ticks: o.horizontal ? { autoSkip: false } : { callback: v => (o.axfmt || o.fmt || fmt.num)(v) } },
      },
    },
  });
}
function doughnut(id, labels, values, o = {}) {
  const tot = values.reduce((a, b) => a + b, 0);
  return mk(id, {
    type: 'doughnut',
    data: { labels, datasets: [{ data: values, backgroundColor: o.colors || PAL, borderWidth: 2, borderColor: '#fff' }] },
    options: {
      cutout: '62%',
      plugins: {
        legend: { position: o.legend || 'right', labels: { boxWidth: 8, padding: 10 } },
        tooltip: { callbacks: { label: c => ` ${c.label}: ${(o.fmt || fmt.num)(c.parsed)} (${fmt.pct(c.parsed / tot)})` } },
      },
    },
  });
}
function comboTrend(id, labels, rev, trx) {
  return mk(id, {
    data: {
      labels, datasets: [
        { type: 'bar', label: 'Penjualan (Rp)', data: rev, backgroundColor: '#0e7c86cc', borderRadius: 5, yAxisID: 'y', maxBarThickness: 38, order: 2 },
        { type: 'line', label: 'Jumlah transaksi', data: trx, borderColor: '#e8a317', backgroundColor: '#e8a317', pointRadius: 3.5, tension: .3, borderWidth: 2.5, yAxisID: 'y1', order: 1 },
      ]
    },
    options: {
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', align: 'end' }, tooltip: { callbacks: { label: c => ' ' + c.dataset.label + ': ' + (c.datasetIndex === 0 ? fmt.rp(c.parsed.y) : fmt.num(c.parsed.y)) } } },
      scales: {
        y: { beginAtZero: true, ticks: { callback: v => fmt.rps(v) }, grid: { color: '#eef1f6' } },
        y1: { beginAtZero: true, position: 'right', grid: { display: false }, ticks: { callback: v => fmt.num(v) } },
        x: { grid: { display: false } },
      },
    },
  });
}

/* --- tooltip global --- */
(function () {
  const t = document.createElement('div'); t.id = 'tip'; document.body.appendChild(t);
  window.tip = {
    show(e, html) { t.innerHTML = html; t.style.opacity = 1; this.move(e); },
    move(e) { t.style.left = Math.min(e.clientX + 14, innerWidth - 270) + 'px'; t.style.top = (e.clientY + 14) + 'px'; },
    hide() { t.style.opacity = 0; },
  };
})();

/* --- network graph (SVG, tata letak melingkar) --- */
function networkGraph(el, edges, o = {}) {
  el = typeof el === 'string' ? document.getElementById(el.replace(/^#/, '')) : el;
  if (!edges || !edges.length) { el.innerHTML = '<div class="empty">Tidak ada pasangan produk yang memenuhi ambang pada filter ini.</div>'; return; }
  const W = 760, H = 520, cx = W / 2, cy = H / 2;
  const deg = {}; edges.forEach(e => { deg[e.a] = (deg[e.a] || 0) + e.lift; deg[e.b] = (deg[e.b] || 0) + e.lift; });
  // kelompokkan komponen terhubung agar produk berpasangan berdekatan
  const adj = {}; edges.forEach(e => { (adj[e.a] = adj[e.a] || []).push(e.b); (adj[e.b] = adj[e.b] || []).push(e.a); });
  const seen = new Set(), order = [];
  Object.keys(deg).sort((x, y) => deg[y] - deg[x]).forEach(n => {
    if (seen.has(n)) return; const st = [n];
    while (st.length) { const u = st.pop(); if (seen.has(u)) continue; seen.add(u); order.push(u); (adj[u] || []).forEach(v => st.push(v)); }
  });
  const N = order.length, pos = {};
  order.forEach((n, i) => { const a = 2 * Math.PI * i / N; pos[n] = { x: cx + 120 * Math.cos(a), y: cy + 120 * Math.sin(a), vx: 0, vy: 0 }; });
  for (let it = 0; it < 400; it++) {
    const t = 1 - it / 400;
    order.forEach(u => { pos[u].fx = (cx - pos[u].x) * 0.012; pos[u].fy = (cy - pos[u].y) * 0.012; });
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      const p = pos[order[i]], q = pos[order[j]]; let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2), f = 5200 / d2;
      p.fx += dx / d * f; p.fy += dy / d * f; q.fx -= dx / d * f; q.fy -= dy / d * f;
    }
    edges.forEach(e => { const p = pos[e.a], q = pos[e.b]; const dx = q.x - p.x, dy = q.y - p.y, d = Math.sqrt(dx * dx + dy * dy) + 0.01, f = (d - 95) * 0.06; p.fx += dx / d * f; p.fy += dy / d * f; q.fx -= dx / d * f; q.fy -= dy / d * f; });
    order.forEach(u => { const p = pos[u]; p.x = Math.min(W - 110, Math.max(110, p.x + Math.max(-12, Math.min(12, p.fx)) * t)); p.y = Math.min(H - 30, Math.max(30, p.y + Math.max(-12, Math.min(12, p.fy)) * t)); });
  }
  order.forEach(n => { pos[n].a = 0; });
  const lmin = Math.min(...edges.map(e => e.lift)), lmax = Math.max(...edges.map(e => e.lift));
  const col = l => { const t = lmax === lmin ? 1 : (l - lmin) / (lmax - lmin); return t > .66 ? '#d9453d' : t > .33 ? '#e8a317' : '#3b6fd4'; };
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Network graph asosiasi produk">`;
  edges.forEach(e => {
    const p = pos[e.a], q = pos[e.b], w = 1.5 + (e.lift - 1) * 2.2;
    s += `<line x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" stroke="${col(e.lift)}" stroke-width="${w}" stroke-opacity=".62" stroke-linecap="round" data-t="${esc(e.a)} ↔ ${esc(e.b)}<br>Lift ${e.lift.toFixed(2)} · Support ${(e.support * 100).toFixed(2)}% · Conf ${(e.confidence * 100).toFixed(1)}%" class="ne"/>`;
  });
  order.forEach(n => {
    const p = pos[n], r = 7 + Math.min(9, deg[n] * 1.6), right = p.x >= cx, lx = p.x + (right ? 1 : -1) * (r + 6);
    s += `<g><circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${o.fill || '#0e7c86'}" stroke="#fff" stroke-width="2.5"/><text x="${lx}" y="${p.y + 4}" text-anchor="${right ? 'start' : 'end'}" font-size="12" font-weight="600" fill="#18212f">${esc(n)}</text></g>`;
  });
  s += '</svg>';
  el.innerHTML = s;
  $$('.ne', el).forEach(l => {
    l.addEventListener('mousemove', e => { l.setAttribute('stroke-opacity', 1); tip.show(e, l.dataset.t); });
    l.addEventListener('mouseleave', () => { l.setAttribute('stroke-opacity', .62); tip.hide(); });
  });
}

/* --- heatmap lift --- */
function liftHeatmap(el, h, opts = {}) {
  el = typeof el === 'string' ? document.getElementById(el.replace(/^#/, '')) : el;
  const names = h.names, L = h.lift, co = h.co;
  const hi = opts.max || 3.2;
  const color = v => {
    if (v == null) return '#f0f2f6';
    if (v >= 1) { const t = Math.min(1, (v - 1) / (hi - 1)); return `rgb(${Math.round(244 - 25 * t)},${Math.round(236 - 160 * t)},${Math.round(220 - 170 * t)})`; }
    const t = Math.min(1, (1 - v) / 0.35); return `rgb(${Math.round(240 - 40 * t)},${Math.round(244 - 26 * t)},${Math.round(250 - 6 * t)})`;
  };
  let s = '<table class="heat"><thead><tr><th></th>' + names.map(n => `<th>${esc(n)}</th>`).join('') + '</tr></thead><tbody>';
  names.forEach((a, i) => {
    s += `<tr><th>${esc(a)}</th>`;
    names.forEach((b, j) => {
      const v = L[i][j];
      s += `<td style="background:${color(v)};color:${v != null && v >= 2 ? '#fff' : '#3b475e'}" data-t="${esc(a)} + ${esc(b)}<br>Lift ${v == null ? '-' : v.toFixed(2)} · ${co[i][j]} nota bersama">${v == null ? '' : (v >= 1.5 ? v.toFixed(1) : '')}</td>`;
    });
    s += '</tr>';
  });
  s += '</tbody></table>';
  el.innerHTML = s;
  $$('td', el).forEach(td => {
    td.addEventListener('mousemove', e => tip.show(e, td.dataset.t));
    td.addEventListener('mouseleave', () => tip.hide());
  });
}

/* --- tabel aturan --- */
function rulesTable(el, rules, o = {}) {
  el = typeof el === 'string' ? document.getElementById(el.replace(/^#/, '')) : el;
  if (!rules || !rules.length) { el.innerHTML = '<div class="empty">Belum ada aturan yang memenuhi ambang support/confidence pada filter ini.</div>'; return; }
  const mx = Math.max(...rules.map(r => r.lift));
  el.innerHTML = `<div class="tbl-wrap ${o.scroll ? 'scroll-y' : ''}"><table class="t compact"><thead><tr><th>#</th><th>Jika membeli (antecedent)</th><th>Maka juga membeli (consequent)</th><th class="r">Nota</th><th class="r">Support</th><th class="r">Confidence</th><th class="r">Lift</th></tr></thead><tbody>` +
    rules.map(r => `<tr><td>${r.rank}</td><td><b>${esc(r.antecedent)}</b></td><td><b>${esc(r.consequent)}</b></td><td class="r">${fmt.num(r.count)}</td><td class="r">${fmt.pct(r.support, 2)}</td><td class="r">${fmt.pct(r.confidence, 1)}</td><td class="r"><div class="bar-cell"><i style="width:${Math.round(52 * r.lift / mx)}px;background:${r.lift >= 2.5 ? '#d9453d' : r.lift >= 1.8 ? '#e8a317' : '#3b6fd4'}"></i><b>${r.lift.toFixed(2)}</b></div></td></tr>`).join('') + '</tbody></table></div>';
}

/* --- sidebar mobile --- */
document.addEventListener('DOMContentLoaded', () => {
  const b = $('.menu-btn'), s = $('.side');
  if (b) b.addEventListener('click', () => s.classList.toggle('open'));
});
