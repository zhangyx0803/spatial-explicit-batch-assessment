'use strict';

/* =========================================================================
   空间显式批量评估工作台 V1.0 —— 前端
   界面全中文；技术标识（英文代码）只在次要位置小字提示。
   ========================================================================= */

const S = {
  boot: null, result: null,
  field: 'est', fields: {}, geom: 'poly',
  selected: new Set(), unitIdx: null,
  busy: false, exported: null, t0: 0,
  openCard: null,
};

let CAT = { op: {}, param: {}, input: {}, mode: {}, stat: {}, impedance: {}, layer_type: {}, field: {}, factor: {}, templates: [] };

const $ = (id) => document.getElementById(id);
const NF = new Intl.NumberFormat('zh-CN');
const PF = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const price = (v) => (v === null || v === undefined || !Number.isFinite(v)) ? '—' : PF.format(v);
const num = (v, d = 2) => (v === null || v === undefined || !Number.isFinite(v)) ? '—' : NF.format(+v.toFixed(d));
const raw = (v, d = 4) => (v === null || v === undefined || !Number.isFinite(v)) ? '—' : v.toFixed(d);
const brief = (v) => {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 10000) return NF.format(Math.round(v));
  if (a >= 100) return v.toFixed(1);
  if (a >= 1) return v.toFixed(3);
  return v.toFixed(4);
};
const pct = (v, d = 1) => (v === null || v === undefined) ? '—' : (v * 100).toFixed(d) + '%';

const opName = (op) => (CAT.op[op] || {}).name || op;
const opDesc = (op) => (CAT.op[op] || {}).desc || '';
const modeName = (m) => CAT.mode[m] || m;
const statName = (s) => CAT.stat[s] || s;
const impName = (t) => CAT.impedance[t] || t;
const pDef = (k) => CAT.param[k] || { name: k, type: 'text' };

/* ---------------- 通信 ---------------- */
async function getJSON(url) {
  const r = await fetch(url);
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || '请求失败');
  return j;
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error || '请求失败');
  return j;
}

let toastT = null;
function toast(msg, isErr) {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(toastT);
  toastT = setTimeout(() => { el.className = 'toast'; }, isErr ? 5600 : 2400);
}

function setBusy(on) {
  S.busy = on;
  $('mapLoading').hidden = !on;
  $('btnExport').disabled = on;
  renderStatus();
}
function tick() {
  $('timer').textContent = S.t0 ? ((performance.now() - S.t0) / 1000).toFixed(1) + ' 秒' : '';
}

/* ---------------- 色带 ---------------- */
const SEQ = ['#fdf6ec', '#fbe3c4', '#f6c68c', '#eda05c', '#d97544', '#b04a34', '#7a2a22'];
const DIV = ['#21618c', '#7fb0cc', '#eef1f4', '#d9a08f', '#a3382b'];

function hex2rgb(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
function ramp(stops, t) {
  t = Math.max(0, Math.min(1, t));
  const n = stops.length - 1, x = t * n;
  const i = Math.min(Math.floor(x), n - 1), f = x - i;
  const a = hex2rgb(stops[i]), b = hex2rgb(stops[i + 1]);
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(a[1] + (b[1] - a[1]) * f)},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}

/* =========================================================================
   地图（按真实坐标绘制，支持不规则点位）
   ========================================================================= */
const MAP = { s: 1, cell: 250, x0: 0, y0: 0, ctx: null, idx: null };

function extentOf() {
  const e = S.boot.project.extent;
  const cell = +S.boot.project.cell || 250;
  return { x0: e[0], y0: e[1], x1: e[2] + cell, y1: e[3] + cell, cell };
}

function layoutMap() {
  const cvs = $('map'), wrap = $('canvasWrap');
  const g = extentOf();
  const wData = Math.max(1, g.x1 - g.x0), hData = Math.max(1, g.y1 - g.y0);
  const availW = Math.max(160, wrap.clientWidth - 20);
  const availH = Math.max(160, wrap.clientHeight - 20);
  const s = Math.min(availW / wData, availH / hData);      // 每米多少像素
  const w = Math.max(80, wData * s), h = Math.max(80, hData * s);
  const dpr = window.devicePixelRatio || 1;

  cvs.style.width = w + 'px';
  cvs.style.height = h + 'px';
  cvs.width = Math.round(w * dpr);
  cvs.height = Math.round(h * dpr);

  const ctx = cvs.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  Object.assign(MAP, { s, cell: g.cell, x0: g.x0, y0: g.y0, ctx });
  return { ctx, w, h, s, g };
}

function fieldPayload() {
  const a = S.result.arrays;
  switch (S.field) {
    case 'est': return { v: a.est_median, unit: '元/m²', div: false, price: true, title: '估值单价（中位口径）' };
    case 'mean': return { v: a.est_mean, unit: '元/m²', div: false, price: true, title: '估值单价（均值口径）' };
    case 'resid': return { v: a.resid, unit: '', div: true, title: '残差' };
    case 'width': {
      const v = a.p_high.map((h, i) => (h != null && a.p_low[i] != null && a.est_median[i])
        ? (h - a.p_low[i]) / a.est_median[i] : null);
      return { v, unit: '', div: false, title: '预测区间相对宽度' };
    }
    default: {
      const code = S.field.slice(7);
      const f = (S.boot.factors || []).find(x => x.code === code);
      return { v: S.fields[code] || [], unit: '', div: false, title: f ? f.name : code, factor: code };
    }
  }
}


/* ===================== 六边形网格 ===================== */
function hexRound(q, r) {
  let x = q, z = r, y = -x - z;
  let rx = Math.round(x), ry = Math.round(y), rz = Math.round(z);
  const dx = Math.abs(rx - x), dy = Math.abs(ry - y), dz = Math.abs(rz - z);
  if (dx > dy && dx > dz) rx = -ry - rz;
  else if (dy > dz) ry = -rx - rz;
  else rz = -rx - ry;
  return [rx, rz];
}

function hexCorners(cx, cy, R) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = Math.PI / 180 * (60 * i + 30);
    pts.push([cx + R * Math.cos(a), cy + R * Math.sin(a)]);
  }
  return pts;
}

/* 把单元聚合到六边形：面积加权平均，避免大单元被小单元稀释 */
function hexAggregate(units, vals, sumW, g) {
  const spanX = g.x1 - g.x0, spanY = g.y1 - g.y0;
  let R = Math.max(150, Math.min(1200, Math.max(spanX, spanY) / 46));
  const w = Math.sqrt(3) * R;
  const buckets = new Map();
  for (let k = 0; k < units.x.length; k++) {
    const v = vals[k];
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    const q = units.x[k] / w - (units.y[k] / (1.5 * R)) / 2;
    const r = units.y[k] / (1.5 * R);
    const [hq, hr] = hexRound(q, r);
    const key = hq + ',' + hr;
    let b = buckets.get(key);
    if (!b) { b = { q: hq, r: hr, sw: 0, sv: 0, n: 0 }; buckets.set(key, b); }
    const wt = sumW ? (sumW[k] || 1) : 1;
    b.sw += wt; b.sv += v * wt; b.n++;
  }
  const out = [];
  for (const b of buckets.values()) {
    const cx = w * (b.q + b.r / 2);
    const cy = 1.5 * R * b.r;
    out.push({ x: cx, y: cy, v: b.sv / (b.sw || 1), n: b.n, R });
  }
  return out;
}

function drawMap() {
  const { ctx, w, h, s, g } = layoutMap();
  const p = fieldPayload();
  const vals = p.v || [];
  const units = S.boot.units;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, w, h);

  const sorted = [];
  for (const x of vals) if (x !== null && x !== undefined && Number.isFinite(x)) sorted.push(p.div ? Math.abs(x) : x);
  sorted.sort((a, b) => a - b);
  const nv = sorted.length;
  const at = (q) => nv ? sorted[Math.min(nv - 1, Math.max(0, Math.floor((nv - 1) * q)))] : 0;
  const lo = at(0.02), mid = at(0.5), hi = at(0.98);
  const rankT = (x) => {
    let a = 0, b = nv - 1;
    while (a <= b) { const m = (a + b) >> 1; if (sorted[m] < x) a = m + 1; else b = m - 1; }
    return nv > 1 ? a / (nv - 1) : 0.5;
  };

  const size = Math.max(1, g.cell * s);
  MAP.idx = new Map();
  const bm = (S.boot && S.boot.basemap) || {};
  const X = (x) => (x - g.x0) * s;
  const Y = (y) => (g.y1 - y) * s;

  // 水体：先铺底，江河水系是最有效的「这是哪儿」视觉锚点
  if (bm.water && bm.water.length) {
    ctx.fillStyle = '#dce8f2';
    ctx.beginPath();
    for (const flat of bm.water) {
      if (!flat || flat.length < 6) continue;
      ctx.moveTo(X(flat[0]), Y(flat[1]));
      for (let i = 2; i < flat.length; i += 2) ctx.lineTo(X(flat[i]), Y(flat[i + 1]));
      ctx.closePath();
    }
    ctx.fill();
  }

  const usePoly = bm.unit_polys && bm.unit_polys.length === units.x.length;
  const mode = S.geom || (usePoly ? 'poly' : 'dot');

  // ---- 六边形网格：等面积聚合，跨区可比，全市视图更清爽 ----
  if (mode === 'hex') {
    const cells = hexAggregate(units, vals, S.boot.units.area, g);
    const hs = cells.map(c => c.v).filter(Number.isFinite).sort((a, b) => a - b);
    const nn = hs.length;
    const qat = (q) => nn ? hs[Math.min(nn - 1, Math.max(0, Math.floor((nn - 1) * q)))] : 0;
    for (const c of cells) {
      const rank = nn > 1 ? (hs.findIndex(t => t >= c.v) / (nn - 1)) : 0.5;
      ctx.beginPath();
      const cs = hexCorners(X(c.x), Y(c.y), c.R * s);
      ctx.moveTo(cs[0][0], cs[0][1]);
      for (let i = 1; i < 6; i++) ctx.lineTo(cs[i][0], cs[i][1]);
      ctx.closePath();
      ctx.fillStyle = p.div
        ? ramp(DIV, 0.5 + 0.5 * Math.sign(c.v) * rankT(Math.abs(c.v)))
        : ramp(SEQ, Math.max(0, Math.min(1, rank)));
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,.55)';
      ctx.lineWidth = 0.5;
      ctx.stroke();
    }
    drawBasemap(ctx, s, g);
    ctx.strokeStyle = '#aeb6bf';
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
    return;
  }

  for (let k = 0; k < units.x.length; k++) {
    const px = (units.x[k] - g.x0) * s;
    const py = (g.y1 - units.y[k]) * s;
    MAP.idx.set(Math.floor((units.x[k] - g.x0) / g.cell) + ',' + Math.floor((units.y[k] - g.y0) / g.cell), k);

    const v = vals[k];
    let color;
    if (v === null || v === undefined || !Number.isFinite(v)) color = '#eef0f3';
    else if (p.div) color = ramp(DIV, 0.5 + 0.5 * Math.sign(v) * rankT(Math.abs(v)));
    else color = ramp(SEQ, rankT(v));

    if (mode === 'poly' && usePoly) {
      const flat = bm.unit_polys[k];
      if (flat && flat.length >= 6) {
        ctx.beginPath();
        ctx.moveTo(X(flat[0]), Y(flat[1]));
        for (let i = 2; i < flat.length; i += 2) ctx.lineTo(X(flat[i]), Y(flat[i + 1]));
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();
        continue;
      }
    }
    ctx.fillStyle = color;
    ctx.fillRect(px, py, Math.ceil(size), Math.ceil(size));
  }

  drawBasemap(ctx, s, g);

  ctx.strokeStyle = '#aeb6bf';
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);

  if (S.unitIdx != null) {
    const ux = (units.x[S.unitIdx] - g.x0) * s;
    const uy = (g.y1 - units.y[S.unitIdx]) * s;
    ctx.strokeStyle = '#11161c';
    ctx.lineWidth = 2;
    ctx.strokeRect(ux - 1, uy - 1, Math.ceil(size) + 2, Math.ceil(size) + 2);
  }

  $('stageTitle').textContent = p.title;
  $('stageUnit').textContent = p.unit;
  const grad = p.div ? DIV : SEQ;
  $('legendBar').style.background = `linear-gradient(90deg,${grad.join(',')})`;
  $('legendScale').textContent = p.div
    ? `${brief(-hi)} · 0 · ${brief(hi)}`
    : `${brief(lo)} · ${brief(mid)} · ${brief(hi)}`;
  $('footLegend').hidden = !p.div;
  $('stageStat').textContent = nv
    ? `样本 ${NF.format(nv)}　中位 ${p.price ? price(mid) : brief(mid)}　P98 ${p.price ? price(hi) : brief(hi)}`
    : '';
  const bmFoot = (S.boot.basemap || {});
  $('footInfo').textContent =
    `单元 ${S.boot.project.n_units} · 道路 ${(bmFoot.roads || []).length} · 水体 ${(bmFoot.water || []).length} · 中心地 ${(bmFoot.centers || []).length} · ${S.result.features.length} 因子`;
}

/* ---- 底图：路网 + 单元轮廓 + 中心地 ---- */
function drawBasemap(ctx, s, g) {
  const bm = S.boot && S.boot.basemap;
  if (!bm) return;
  const X = (x) => (x - g.x0) * s;
  const Y = (y) => (g.y1 - y) * s;

  // 全路网：细线叠加在色块上，既保留地理骨架又不压配色
  if (bm.roads && bm.roads.length) {
    ctx.strokeStyle = 'rgba(74,86,100,.30)';
    ctx.lineWidth = Math.max(0.5, s * 5);
    ctx.lineCap = 'round';
    ctx.beginPath();
    for (const flat of bm.roads) {
      if (!flat || flat.length < 4) continue;
      ctx.moveTo(X(flat[0]), Y(flat[1]));
      for (let i = 2; i < flat.length; i += 2) ctx.lineTo(X(flat[i]), Y(flat[i + 1]));
    }
    ctx.stroke();
  }

  // 单元轮廓：极细白线，让相邻面块有分隔感但不割裂
  if (bm.boundaries && bm.boundaries.length) {
    ctx.strokeStyle = 'rgba(255,255,255,.28)';
    ctx.lineWidth = 0.6;
    ctx.beginPath();
    for (const flat of bm.boundaries) {
      if (!flat || flat.length < 6) continue;
      ctx.moveTo(X(flat[0]), Y(flat[1]));
      for (let i = 2; i < flat.length; i += 2) ctx.lineTo(X(flat[i]), Y(flat[i + 1]));
      ctx.closePath();
    }
    ctx.stroke();
  }

  // 中心地
  if (bm.centers && bm.centers.length) {
    const col = { 1: '#7d2a1c', 2: '#a86f16', 3: '#2f5f7d' };
    for (const c of bm.centers) {
      const r = c.level === 1 ? 6 : (c.level === 2 ? 4.3 : 2.8);
      ctx.beginPath();
      ctx.arc(X(c.x), Y(c.y), r, 0, Math.PI * 2);
      ctx.fillStyle = col[c.level] || '#666';
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.3;
      ctx.stroke();
    }
  }
}

function hitTest(ev) {
  const rect = $('map').getBoundingClientRect();
  const g = extentOf();
  const dx = (ev.clientX - rect.left) / MAP.s + g.x0;
  const dy = g.y1 - (ev.clientY - rect.top) / MAP.s;
  return MAP.idx.get(Math.floor((dx - g.x0) / g.cell) + ',' + Math.floor((dy - g.y0) / g.cell)) ?? null;
}

function showTip(ev, text) {
  const tip = $('tip'), wrap = $('canvasWrap');
  const wr = wrap.getBoundingClientRect();
  tip.textContent = text;
  tip.hidden = false;
  tip.style.left = '0px'; tip.style.top = '0px';
  tip.style.transform = 'translate(-50%,-128%)';
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  let x = ev.clientX - wr.left, y = ev.clientY - wr.top;
  const minX = tw / 2 + 3, maxX = wr.width - tw / 2 - 3;
  x = Math.min(Math.max(x, minX), Math.max(minX, maxX));
  if (y - th - 8 < 0) {
    tip.style.transform = 'translate(-50%, 12px)';
    y = Math.min(Math.max(y, 2), wr.height - th - 12);
  } else {
    y = Math.min(Math.max(y, th + 8), wr.height - 4);
  }
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}

/* =========================================================================
   左栏
   ========================================================================= */
function renderStatus() {
  const b = S.boot;
  if (!b) return;
  const r = S.result;
  const rows = [
    ['数据接入', `${NF.format(b.project.n_units)} 个单元 / ${NF.format(b.project.n_obs)} 条成交`],
    ['因子计算', `${b.project.engine_factors} 个（缓存复用 ${b.project.cache_hits}）`],
    ['模型训练', r ? `R² ${raw(r.metrics.train.r2, 3)}　${r.features.length} 个因子` : '—'],
    ['批量估值', r ? `${NF.format(b.project.n_units)} 条` : '—'],
    ['空间诊断', r ? `Moran's I ${raw(r.moran.i, 3)}　p ${raw(r.moran.p, 3)}` : '—'],
    ['成果输出', S.exported ? `已导出 ${S.exported} 个文件` : (S.busy ? '进行中' : '未导出')],
  ];
  $('statusList').innerHTML = rows.map(([t, v], i) =>
    `<div class="row${S.busy && i === 2 ? ' busy' : ' done'}">
       <span class="n">${i + 1}</span><span class="t">${t}</span><span class="v">${v}</span>
     </div>`).join('');
}

function renderMeta() {
  const b = S.boot, p = b.project, n = b.network;
  const rows = [
    ['评估单元', NF.format(p.n_units)],
    ['成交样本', NF.format(p.n_obs)],
    ['单元尺寸', `${num(p.cell, 0)} 米`],
    ['数据来源', p.source === 'user' ? '我的数据' : '演示数据'],
    ['坐标系', p.crs],
    ['路网节点', NF.format(n.n_nodes)],
    ['连通分量', NF.format(n.n_components)],
    ['吸附失败率', pct(n.snap_fail, 2)],
    ['平均吸附距离', `${num(n.snap_mean_dist, 0)} 米`],
    ['因子数量', NF.format(b.factors.length)],
  ];
  $('metaList').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  $('projName').textContent = `${p.name} · 运行 ${p.run_id}`;
}

function renderFieldSelect() {
  const sel = $('fieldSel');
  const out = [
    ['est', '估值单价（中位口径）'],
    ['mean', '估值单价（均值口径）'],
    ['width', '预测区间宽度'],
    ['resid', '残差（高估/低估）'],
  ];
  const fac = (S.boot.factors || []).map(f => ['factor:' + f.code, '因子：' + f.name]);
  sel.innerHTML =
    `<optgroup label="成果图层">${out.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</optgroup>` +
    `<optgroup label="因子图层">${fac.map(([v, t]) => `<option value="${v}">${t}</option>`).join('')}</optgroup>`;
  sel.value = S.field;
  sel.onchange = async () => {
    S.field = sel.value;
    if (S.field.startsWith('factor:')) {
      const code = S.field.slice(7);
      if (!S.fields[code]) {
        try { S.fields[code] = (await getJSON('/api/field?code=' + encodeURIComponent(code))).values; }
        catch (e) { toast(e.message, true); }
      }
    }
    drawMap();
  };
}

function renderLayers() {
  $('layerList').innerHTML = (S.boot.layers || []).map(l =>
    `<div class="lrow${l.used ? ' used' : ''}">
       <span class="id" title="${l.id}">${l.name}${l.n ? `（${NF.format(l.n)}）` : ''}</span>
       <span class="ty">${l.type_cn}</span>
     </div>`).join('');
}

/* =========================================================================
   右栏：模型
   ========================================================================= */
function renderMetrics() {
  const r = S.result, m = r.metrics;
  const codOk = r.ratio.cod != null && r.ratio.cod <= r.ratio.cod_max;
  const prdOk = r.ratio.prd != null && r.ratio.prd >= r.ratio.prd_low && r.ratio.prd <= r.ratio.prd_high;
  const moranOk = r.moran.p != null && r.moran.p >= 0.05;
  const items = [
    ['拟合度 R²（训练）', raw(m.train.r2, 3), m.train.r2 >= .85 ? 'ok' : 'mid'],
    ['拟合度 R²（空间留块）', raw(m.cv_spatial.r2, 3), m.cv_spatial.r2 >= .85 ? 'ok' : 'mid'],
    ['平均误差 MAPE', raw(m.cv_spatial.mape, 1) + '%', m.cv_spatial.mape <= 20 ? 'ok' : 'bad'],
    ['离散系数 COD', raw(r.ratio.cod, 1), codOk ? 'ok' : 'bad'],
    ['价格相关差 PRD', raw(r.ratio.prd, 3), prdOk ? 'ok' : 'bad'],
    ["残差空间自相关", raw(r.moran.i, 3), moranOk ? 'ok' : 'bad'],
  ];
  $('metrics').innerHTML = items.map(([k, v, c]) =>
    `<div class="mrow"><span class="k">${k}</span><span class="v ${c}">${v}</span></div>`).join('');
}

function renderFeatures() {
  const sel = S.selected;
  const list = (S.boot.factors || []).slice().sort((a, b) => {
    const pa = a.code.startsWith('b_placebo') ? 1 : 0;
    const pb = b.code.startsWith('b_placebo') ? 1 : 0;
    return pa - pb;
  });
  $('featList').innerHTML = list.map(f => `
    <label class="frow${f.code.startsWith('b_placebo') ? ' placebo' : ''}">
      <input type="checkbox" data-code="${f.code}" ${sel.has(f.code) ? 'checked' : ''}>
      <span class="code" style="font-family:inherit;font-size:11px">${f.name}</span>
      <span class="op">${f.op_name}</span>
    </label>`).join('');
  $('featList').querySelectorAll('input').forEach(inp => {
    inp.onchange = () => {
      if (inp.checked) sel.add(inp.dataset.code); else sel.delete(inp.dataset.code);
      $('featCount').textContent = `（${sel.size}/${S.boot.factors.length}）`;
      scheduleRun();
    };
  });
  $('featCount').textContent = `（${sel.size}/${S.boot.factors.length}）`;
}

function renderCoef() {
  $('coefTbl').querySelector('tbody').innerHTML = S.result.coef.map(r => {
    const [name, coef, se, t, p, star] = r;
    return `<tr><td class="txt">${name}</td><td class="r">${coef}</td><td class="r">${t}</td>
            <td class="r">${p}</td><td class="r ${star ? 'sig' : 'ns'}">${star || '·'}</td></tr>`;
  }).join('');
}

function renderVif() {
  $('vifTbl').querySelector('tbody').innerHTML = S.result.vif.slice(0, 6).map(([n, r2, v]) => {
    const cls = v > 10 ? 'hi' : (v > 5 ? 'sig' : '');
    return `<tr><td class="txt">${n}</td><td class="r ${cls}">${v.toFixed(2)}</td></tr>`;
  }).join('');
}

function renderDiag() {
  const mo = S.result.moran;
  const bad = mo.p < 0.05 && mo.i > mo.e;
  $('moranCard').innerHTML = `
    <div class="big ${bad ? 'bad' : ''}">${raw(mo.i, 4)}</div>
    <div class="sub">期望值 ${raw(mo.e, 4)} · z ${raw(mo.z, 2)} · p ${raw(mo.p, 4)} · ${mo.n_perm} 次随机置换</div>
    <div class="verdict">${mo.verdict}</div>`;

  $('distTbl').querySelector('tbody').innerHTML = S.result.districts.slice(0, 12).map(d => {
    const cls = d.tag.includes('低估') ? 'sig' : (d.tag.includes('高估') ? 'hi' : 'ns');
    return `<tr><td class="txt">${d.code}</td><td class="r">${d.mean.toFixed(3)}</td>
            <td class="r">${d.n}</td><td class="txt ${cls}">${d.tag}</td></tr>`;
  }).join('');

  const ra = S.result.ratio;
  const codOk = ra.cod != null && ra.cod <= ra.cod_max;
  const prdOk = ra.prd != null && ra.prd >= ra.prd_low && ra.prd <= ra.prd_high;
  $('ratioCard').innerHTML = [
    ['中位比率', raw(ra.median_ratio, 3), 'mid'],
    ['样本量', NF.format(ra.n), 'mid'],
    ['COD（越小越好）', raw(ra.cod, 1), codOk ? 'ok' : 'bad'],
    ['PRD（接近 1 为好）', raw(ra.prd, 3), prdOk ? 'ok' : 'bad'],
  ].map(([k, v, c]) => `<div class="mrow"><span class="k">${k}</span><span class="v ${c}">${v}</span></div>`).join('');
}

async function showUnit(idx) {
  S.unitIdx = idx;
  drawMap();
  if (S.tab === 'decomp') { showDecomp(idx); }
  try {
    const u = await getJSON('/api/unit?i=' + idx);
    $('unitEmpty').hidden = true;
    $('unitBody').hidden = false;
    $('uId').textContent = u.unit_id;
    $('uAdmin').textContent = `${u.admin} · 坐标 ${num(u.x, 0)}, ${num(u.y, 0)} · ${num(u.area, 0)} ㎡`;

    const items = [
      ['估值单价（中位）', price(u.est_median) + ' 元/㎡', 'mid'],
      ['估值单价（均值）', price(u.est_mean) + ' 元/㎡', 'mid'],
      ['价格下限 P10', price(u.p_low) + ' 元/㎡', 'mid'],
      ['价格上限 P90', price(u.p_high) + ' 元/㎡', 'mid'],
      ['残差', u.resid == null ? '本单元无成交' : raw(u.resid, 3),
        u.resid == null ? 'mid' : (u.resid > 0 ? 'bad' : 'ok')],
      ['成交单价', u.obs ? price(u.obs.sale_unit_price) + ' 元/㎡' : '—', 'mid'],
    ];
    $('uMetrics').innerHTML = items.map(([k, v, c]) =>
      `<div class="mrow" style="grid-column:span 2"><span class="k">${k}</span>
        <span class="v ${c}" style="font-size:11px">${v}</span></div>`).join('');

    $('uFactorTbl').querySelector('tbody').innerHTML = u.factors.map(f => `
      <tr><td class="txt">${f.name}</td><td class="r">${brief(f.value)}</td>
      <td class="r ${f.selected ? 'sig' : 'ns'}">${f.selected ? '✓' : ''}</td></tr>`).join('');
  } catch (e) { toast(e.message, true); }
}

/* =========================================================================
   右栏：因子设置
   ========================================================================= */
function renderFactorCards() {
  const box = $('factorCards');
  box.innerHTML = (S.boot.factors || []).map(f => {
    const open = S.openCard === f.code;
    return `<div class="fcard${f.selected ? '' : ' off'}" data-code="${f.code}">
      <div class="fcard-h" data-toggle="${f.code}">
        <input type="checkbox" data-en="${f.code}" ${f.selected ? 'checked' : ''} title="参与建模">
        <span class="nm">${f.name}</span>
        <span class="op">${f.op_name}</span>
        <span class="ex">${open ? '收起' : '设置'}</span>
      </div>
      <div class="fcard-b" ${open ? '' : 'hidden'}>
        <div class="form">${paramForm(f)}</div>
        <div class="row2">
          <button class="btn small" data-save="${f.code}">保存并重算</button>
          <span class="ename">内部标识 ${f.code}</span>
        </div>
      </div>
    </div>`;
  }).join('');

  box.querySelectorAll('[data-toggle]').forEach(el => {
    el.onclick = (ev) => {
      if (ev.target.tagName === 'INPUT') return;
      const code = el.dataset.toggle;
      S.openCard = S.openCard === code ? null : code;
      renderFactorCards();
    };
  });
  box.querySelectorAll('[data-en]').forEach(el => {
    el.onchange = async () => {
      const code = el.dataset.en;
      setBusy(true);
      try {
        const j = await postJSON('/api/factors/update', { changes: { [code]: { enabled: el.checked } } });
        adopt(j);
        toast('已更新：' + code);
      } catch (e) { toast(e.message, true); }
      finally { setBusy(false); }
    };
  });
  box.querySelectorAll('[data-save]').forEach(el => {
    el.onclick = async () => {
      const code = el.dataset.save;
      const card = box.querySelector(`.fcard[data-code="${code}"]`);
      try {
        const params = readParamForm(card);
        setBusy(true);
        const j = await postJSON('/api/factors/update', { changes: { [code]: { params } } });
        adopt(j);
        toast('参数已保存，模型已重算');
      } catch (e) { toast(e.message, true); }
      finally { setBusy(false); }
    };
  });
}

function paramForm(f) {
  const keys = Object.keys(f.params || {});
  if (!keys.length) return `<label>参数</label><span class="muted">该因子没有可调参数</span>`;
  return keys.map(k => {
    const d = pDef(k);
    const v = f.params[k];
    let ctrl = '';
    if (d.type === 'select') {
      ctrl = `<select class="select" data-p="${k}">` + d.options.map(o =>
        `<option value="${o}" ${o === v ? 'selected' : ''}>${k === 'mode' ? modeName(o) : statName(o)}</option>`).join('') + `</select>`;
    } else if (d.type === 'numbers') {
      ctrl = `<input class="input" data-p="${k}" data-t="numbers" value="${Array.isArray(v) ? v.join(', ') : v}">`;
    } else if (d.type === 'impedance') {
      const t = (v && v.type) || 'exponential';
      const beta = (v && (v.beta ?? v.sigma ?? v.sigma_min)) ?? 0.08;
      ctrl = `<div style="display:flex;gap:5px">
        <select class="select" data-p="${k}" data-sub="type" style="flex:1">
          ${Object.keys(CAT.impedance).map(o => `<option value="${o}" ${o === t ? 'selected' : ''}>${impName(o)}</option>`).join('')}
        </select>
        <input class="input" data-p="${k}" data-sub="beta" style="width:88px" type="number" step="0.01" value="${beta}" title="衰减强度">
      </div>`;
    } else if (d.type === 'snap') {
      const md = (v && v.max_dist_m) || 300;
      ctrl = `<input class="input" data-p="${k}" data-sub="max_dist_m" type="number" step="50" value="${md}">`;
    } else {
      ctrl = `<input class="input" data-p="${k}" data-t="number" type="number" step="${d.step || 1}" value="${v}">`;
    }
    const unit = d.unit ? `（${d.unit}）` : '';
    return `<label>${d.name}${unit}</label>${ctrl}`;
  }).join('');
}

function readParamForm(card) {
  const out = {};
  card.querySelectorAll('[data-p]').forEach(el => {
    const k = el.dataset.p, sub = el.dataset.sub, t = el.dataset.t;
    if (sub) {
      out[k] = out[k] || {};
      out[k][sub] = sub === 'type' ? el.value : +el.value;
    } else if (t === 'numbers') {
      out[k] = el.value.split(/[,，\s]+/).filter(Boolean).map(Number);
    } else if (t === 'number') {
      out[k] = +el.value;
    } else {
      out[k] = el.value;
    }
  });
  // 阻抗参数统一成 {type, beta|sigma}
  Object.keys(out).forEach(k => {
    const v = out[k];
    if (v && typeof v === 'object' && 'type' in v) {
      if (v.type === 'gaussian') { out[k] = { type: 'gaussian', sigma: v.beta ?? 8 }; }
      else { out[k] = { type: v.type, beta: v.beta ?? 0.08 }; }
    }
  });
  return out;
}

/* ---- 新增因子 ---- */
function renderTemplates() {
  const sel = $('tplSel');
  sel.innerHTML = (CAT.templates || []).map(t => `<option value="${t.key}">${t.name}</option>`).join('');
  sel.onchange = renderTplForm;
  renderTplForm();
}

function renderTplForm() {
  const key = $('tplSel').value;
  const tpl = (CAT.templates || []).find(t => t.key === key);
  if (!tpl) return;
  $('tplName').value = tpl.name;

  const kindLabel = { network: '路网图层', point: '点图层', polygon: '面图层', raster: '栅格图层' };
  $('tplInputs').innerHTML = Object.entries(tpl.inputs).map(([slot, kind]) => {
    const opts = (S.boot.layers || []).filter(l => (l.type || '').toLowerCase() === kind);
    const cn = (CAT.input && CAT.input[slot]) || slot;
    if (!opts.length) {
      return `<label>${cn}</label><span class="muted">没有可用的${kindLabel[kind] || kind}</span>`;
    }
    return `<label>${cn}</label><select class="select" data-slot="${slot}">` +
      opts.map(l => `<option value="${l.id}">${l.name}</option>`).join('') + `</select>`;
  }).join('');

  $('tplParams').innerHTML = Object.keys(tpl.params || {}).map(k => {
    const d = pDef(k);
    const v = tpl.params[k];
    if (d.type === 'select') {
      return `<label>${d.name}</label><select class="select" data-tp="${k}">` +
        d.options.map(o => `<option value="${o}" ${o === v ? 'selected' : ''}>${statName(o)}</option>`).join('') + `</select>`;
    }
    const num = (v && typeof v === 'object') ? (v.beta ?? v.sigma ?? 1) : v;
    return `<label>${d.name}${d.unit ? '（' + d.unit + '）' : ''}</label>
            <input class="input" data-tp="${k}" type="number" step="${d.step || 1}" value="${num}">`;
  }).join('');
}

async function addFactor() {
  const tpl = (CAT.templates || []).find(t => t.key === $('tplSel').value);
  if (!tpl) return;
  const mapping = {};
  $('tplInputs').querySelectorAll('[data-slot]').forEach(el => { mapping[el.dataset.slot] = el.value; });
  const params = {};
  $('tplParams').querySelectorAll('[data-tp]').forEach(el => {
    const k = el.dataset.tp, d = pDef(k);
    params[k] = d.type === 'select' ? el.value : +el.value;
  });
  try {
    setBusy(true);
    const j = await postJSON('/api/factors/add', {
      template: tpl.key, name: $('tplName').value || tpl.name, mapping, params,
    });
    adopt(j);
    toast('已新增因子：' + (j.name || ''));
    $('addBox').hidden = true;
  } catch (e) { toast(e.message, true); }
  finally { setBusy(false); }
}

/* =========================================================================
   运行
   ========================================================================= */
let runTimer = null;
function scheduleRun() { clearTimeout(runTimer); runTimer = setTimeout(doRun, 300); }

async function doRun() {
  if (S.busy) return;
  if (S.selected.size === 0) { toast('至少要选择一个因子', true); return; }
  setBusy(true);
  S.t0 = performance.now();
  const t = setInterval(tick, 100);
  try {
    const res = await postJSON('/api/run', { features: Array.from(S.selected) });
    S.result = res;
    renderAll();
  } catch (e) { toast('计算失败：' + e.message, true); }
  finally { clearInterval(t); setBusy(false); S.t0 = 0; tick(); }
}

function adopt(payload) {
  S.boot = payload;
  CAT = payload.catalog || CAT;
  S.result = payload.result;
  S.selected = new Set(payload.result.features);
  S.fields = {};
  S.unitIdx = null;
  renderMeta(); renderFieldSelect(); renderAll();
}

function renderAll() {
  renderStatus(); renderMetrics(); renderFeatures(); renderCoef(); renderVif();
  renderDiag(); renderLayers(); renderFactorCards(); renderTemplates(); drawMap();
}

/* =========================================================================
   数据导入
   ========================================================================= */
const SLOTS = [
  {
    kind: 'units', title: '① 评估单元', req: true,
    keys: [['id', '单元编号'], ['lon', '经度'], ['lat', '纬度'], ['x', 'X 坐标'], ['y', 'Y 坐标'],
           ['admin', '行政区'], ['population', '常住人口']],
    tip: '每个评估单元一行。有经纬度就选经纬度列，有投影坐标就选 X/Y 列。',
  },
  {
    kind: 'obs', title: '② 成交记录', req: true,
    keys: [['unit_id', '单元编号'], ['unit_price', '成交单价'], ['price', '成交总价'], ['date', '成交日期']],
    tip: '至少要有单元编号 + 单价（或总价）；总价会按上面的套均面积换算成单价。',
  },
  {
    kind: 'network', title: '③ 道路网', req: false,
    keys: [['fx', '起点 X/经度'], ['fy', '起点 Y/纬度'], ['tx', '终点 X/经度'],
           ['ty', '终点 Y/纬度'], ['cls', '道路等级'], ['oneway', '是否单向']],
    tip: '一行一条路段。不导入时系统会生成示意路网，路网类因子仅作演示。',
  },
  {
    kind: 'layer', title: '④ 设施点位', req: false, multi: true,
    keys: [['lon', '经度'], ['lat', '纬度'], ['x', 'X 坐标'], ['y', 'Y 坐标'], ['weight', '权重/容量']],
    tip: '学校、医院、地铁站、商业点等，可导入多份。',
  },
];

const IMP = { units: null, obs: null, network: null, layers: [] };

function toB64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

function renderSlots() {
  $('slotList').innerHTML = SLOTS.map(slot => {
    const one = IMP[slot.kind];
    return `<div class="slot" data-kind="${slot.kind}">
      <div class="slot-h">
        ${slot.title}
        ${slot.req ? '<span class="req">必需</span>' : '<span class="opt">可选</span>'}
        <input type="file" class="file" accept=".csv,.txt,.tsv" data-kind="${slot.kind}" ${slot.multi ? 'multiple' : ''}>
      </div>
      <div class="slot-body">
        ${slot.multi ? renderLayerSlots() : (one ? mappingHTML(slot, one) : `<div class="slot-tip">${slot.tip}</div>`)}
        ${slot.multi ? '' : (one ? '' : '')}
      </div>
    </div>`;
  }).join('');

  $('slotList').querySelectorAll('input[type=file]').forEach(inp => {
    inp.onchange = () => pickFiles(inp);
  });
  bindMappings();
  $('slotList').querySelectorAll('[data-lname]').forEach(inp => {
    inp.oninput = () => {
      const k = +inp.dataset.lname;
      if (IMP.layers[k]) IMP.layers[k].name = inp.value;
    };
  });
}

function renderLayerSlots() {
  if (!IMP.layers.length) return `<div class="slot-tip">尚未选择文件（学校、医院、地铁站、商业网点等，可多选）</div>`;
  return IMP.layers.map((ly, i) => `
    <div style="border-top:1px solid var(--line-soft);padding-top:6px;margin-top:6px">
      <input class="input name" data-lname="${i}" value="${ly.name}" placeholder="给这份图层起个名字，如「学校」">
      ${mappingHTML({ kind: 'layer', keys: SLOTS[3].keys }, ly, 'L' + i)}
    </div>`).join('');
}

function mappingHTML(slot, one, prefix = '') {
  return `<div class="mapgrid">` + slot.keys.map(([k, label]) => {
    const cur = (one.map || {})[k] || '';
    const opts = ['<option value="">（不使用）</option>'].concat(
      one.columns.map(c => `<option value="${c}" ${c === cur ? 'selected' : ''}>${c}</option>`)).join('');
    return `<div class="cell"><span>${label}</span>
      <select data-map="${prefix}|${slot.kind}|${k}">${opts}</select></div>`;
  }).join('') + `</div><div class="slot-tip">共 ${one.rows} 行，识别到 ${one.columns.length} 列</div>`;
}

function bindMappings() {
  $('slotList').querySelectorAll('[data-map]').forEach(el => {
    el.onchange = () => {
      const [prefix, kind, key] = el.dataset.map.split('|');
      if (prefix) {
        const i = +prefix.slice(1);
        if (IMP.layers[i]) IMP.layers[i].map[key] = el.value;
      } else if (IMP[kind]) {
        IMP[kind].map[key] = el.value;
      }
    };
  });
}

async function pickFiles(inp) {
  const files = Array.from(inp.files || []);
  if (!files.length) return;
  const kind = inp.dataset.kind;
  const targets = kind === 'layer' ? files : [files[0]];

  for (let i = 0; i < targets.length; i++) {
    const file = targets[i];
    try {
      const buf = await file.arrayBuffer();
      const b64 = toB64(buf);
      const info = await postJSON('/api/preview', { b64, kind });
      const rec = {
        b64, name: file.name.replace(/\.[^.]+$/, ''),
        columns: info.columns, rows: info.rows,
        map: Object.fromEntries(Object.entries(info.guess || {}).map(([k, v]) => [k, v || ''])),
      };
      if (kind === 'layer') IMP.layers.push(rec);
      else IMP[kind] = rec;
    } catch (e) {
      toast(`${file.name} 解析失败：${e.message}`, true);
    }
  }
  renderSlots();
}

function collectSpec() {
  const spec = {
    project_name: $('impName').value.trim() || '我的工程',
    cell_m: +$('impCell').value || 250,
    avg_area_m2: +$('impAvg').value || 90,
    units: IMP.units ? { b64: IMP.units.b64, map: IMP.units.map } : null,
    obs: IMP.obs ? { b64: IMP.obs.b64, map: IMP.obs.map } : null,
    network: IMP.network ? { b64: IMP.network.b64, map: IMP.network.map } : null,
    layers: IMP.layers.map((ly, i) => ({
      id: `user_layer_${i + 1}`, name: ly.name || `图层${i + 1}`,
      b64: ly.b64, map: ly.map, kind: 'point',
    })),
  };
  return spec;
}

async function applyImport() {
  if (!IMP.units) { toast('请先选择「评估单元」文件', true); return; }
  if (!IMP.obs) { toast('请先选择「成交记录」文件', true); return; }
  try {
    setBusy(true);
    const j = await postJSON('/api/import', { spec: collectSpec() });
    adopt(j);
    $('importNotes').innerHTML = (j.notes || []).map(n => `<p>· ${n}</p>`).join('');
    $('importModal').hidden = true;
    toast('数据导入完成');
  } catch (e) { toast('导入失败：' + e.message, true); }
  finally { setBusy(false); }
}

async function resetDemo() {
  try {
    setBusy(true);
    const j = await postJSON('/api/reset', {});
    IMP.units = IMP.obs = IMP.network = null; IMP.layers = [];
    renderSlots();
    $('importNotes').innerHTML = '';
    adopt(j);
    $('importModal').hidden = true;
    toast('已恢复演示数据');
  } catch (e) { toast(e.message, true); }
  finally { setBusy(false); }
}

/* =========================================================================
   启动与事件
   ========================================================================= */
async function boot() {
  try {
    const b = await getJSON('/api/bootstrap');
    adopt(b);
    const q = new URLSearchParams(location.search);
    const tab = q.get('tab');
    if (tab && ['model', 'diag', 'unit', 'factor'].includes(tab)) switchTab(tab);
    const field = q.get('field');
    if (field) { S.field = field; $('fieldSel').value = field; drawMap(); }
    if (q.get('data')) { renderSlots(); $('importModal').hidden = false; }
    const unit = q.get('unit');
    if (unit !== null && unit !== '' && !Number.isNaN(+unit)) { switchTab('unit'); await showUnit(+unit); }
  } catch (e) {
    toast('加载失败：' + e.message, true);
    console.error(e);
  }
}

$('map').addEventListener('mousemove', (ev) => {
  if (!S.result) return;
  const k = hitTest(ev);
  if (k === null) { $('tip').hidden = true; return; }
  const p = fieldPayload();
  const v = (p.v || [])[k];
  const id = S.boot.units.id[k];
  showTip(ev, (v === null || v === undefined) ? `${id} · 无成交`
    : (p.price ? `${id} · ${price(v)} 元/㎡` : `${id} · ${brief(v)}`));
});
$('map').addEventListener('mouseleave', () => { $('tip').hidden = true; });
$('map').addEventListener('click', (ev) => {
  const k = hitTest(ev);
  if (k === null) return;
  switchTab('unit');
  showUnit(k);
});

$('tabs').addEventListener('click', (ev) => {
  const b = ev.target.closest('.tab');
  if (b) switchTab(b.dataset.tab);
});
function switchTab(name) {
  S.tab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  if (name === 'decomp' && S.unitIdx != null && !DEC.data) { showDecomp(S.unitIdx); }
  ['model', 'diag', 'unit', 'factor', 'decomp'].forEach(n => { $('tab-' + n).hidden = (n !== name); });
}

$('btnAll').onclick = () => { S.boot.factors.forEach(f => S.selected.add(f.code)); renderFeatures(); scheduleRun(); };
$('btnValid').onclick = () => {
  S.selected = new Set(S.boot.factors.filter(f => !f.code.startsWith('b_placebo')).map(f => f.code));
  renderFeatures(); scheduleRun();
};
$('btnReload').onclick = doRun;

$('btnData').onclick = () => { renderSlots(); $('importModal').hidden = false; };
$('impClose').onclick = () => { $('importModal').hidden = true; };
$('impCancel').onclick = () => { $('importModal').hidden = true; };
$('impApply').onclick = applyImport;
$('impReset').onclick = resetDemo;

$('btnAddToggle').onclick = () => {
  $('addBox').hidden = !$('addBox').hidden;
  $('btnAddToggle').textContent = $('addBox').hidden ? '展开' : '收起';
};
$('btnAddFactor').onclick = addFactor;

$('btnExport').onclick = async () => {
  setBusy(true);
  try {
    const j = await postJSON('/api/export', {});
    S.exported = j.files.length;
    renderStatus();
    toast('已导出到 ' + j.dir);
    window.open('/files/' + encodeURIComponent(j.files[0]), '_blank');
  } catch (e) { toast('导出失败：' + e.message, true); }
  finally { setBusy(false); }
};

let rz = null;
window.addEventListener('resize', () => {
  clearTimeout(rz);
  rz = setTimeout(() => { if (S.result) drawMap(); }, 100);
});

boot();

/* ---- 几何显示方式切换 ---- */
const GEOM_HINT = {
  poly: '按真实村/居委边界填色，能逐块核对，边界即行政单元。',
  hex: '等面积六边形网格（边长随范围自适应），跨区块可比，全市视图更清爽。',
  dot: '在每个单元质心画方块，最轻量，适合密集小单元。',
};
(function wireGeom() {
  const box = $('geomSeg');
  if (!box) return;
  box.querySelectorAll('.segbtn').forEach(b => {
    b.onclick = () => {
      box.querySelectorAll('.segbtn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      S.geom = b.dataset.geom;
      const h = $('geomHint');
      if (h) h.textContent = GEOM_HINT[S.geom] || '';
      drawMap();
    };
  });
  // 支持 #hex / #dot 直达（便于演示与截图）
  const h = location.hash.replace('#', '');
  if (h === 'hex' || h === 'dot' || h === 'poly') {
    const tb = box.querySelector('[data-geom="' + h + '"]');
    if (tb) setTimeout(() => tb.click(), 500);
  }
  window.wiredGeom = true;
})();

/* =========================================================================
   右栏：价格拆解 + 个性化适配
   ========================================================================= */
const DEC = { data: null, pref: {}, idx: null };

async function showDecomp(idx) {
  if (idx == null) return;
  DEC.idx = idx;
  $('decompEmpty').hidden = true;
  $('decompBody').hidden = false;
  $('dcTbl').querySelector('tbody').innerHTML =
    '<tr><td colspan="4" class="muted" style="padding:14px">正在拆解……（首次约 1–3 秒）</td></tr>';
  try {
    const d = await postJSON('/api/decompose', { i: idx, price: null, radius: 1500, min_n: 120 });
    DEC.data = d;
    DEC.pref = {};
    d.items.forEach(it => { DEC.pref[it.code] = 1; });
    renderDecomp();
  } catch (e) {
    $('dcTbl').querySelector('tbody').innerHTML =
      '<tr><td colspan="4" class="bad" style="padding:14px">' + e.message + '</td></tr>';
  }
}

async function rerunDecomp() {
  if (DEC.idx == null) return;
  const p = parseFloat($('dcPrice').value) || null;
  $('dcTbl').querySelector('tbody').innerHTML =
    '<tr><td colspan="4" class="muted" style="padding:14px">正在按新价格重新拆解……</td></tr>';
  try {
    const d = await postJSON('/api/decompose', { i: DEC.idx, price: p, radius: 1500, min_n: 120 });
    DEC.data = d;
    d.items.forEach(it => { if (!(it.code in DEC.pref)) DEC.pref[it.code] = 1; });
    renderDecomp();
  } catch (e) { toast(e.message, true); }
}

function renderDecomp() {
  const d = DEC.data;
  if (!d) return;
  $('dcUnit').textContent = d.unit_id;
  $('dcMeta').textContent = '　周边 ' + Math.round(d.radius) + ' 米　' + d.n_samples + ' 套成交　R²=' + d.r2.toFixed(2);
  $('dcPrice').value = Math.round(d.asking_price);
  $('dcBase').textContent = price(d.base_price);
  $('dcModel').textContent = price(d.model_price);
  const ue = d.unexplained;
  const ueCls = Math.abs(ue) / d.asking_price > 0.15 ? 'warn' : '';
  $('dcUnexp').innerHTML = '<span class="' + ueCls + '">' + (ue >= 0 ? '+' : '') + price(ue) + '</span>';
  $('dcSample').textContent = d.n_samples + ' 套';

  const issues = [];
  if (d.n_samples < 100) issues.push('样本仅 ' + d.n_samples + ' 套，系数估计不稳');
  if (d.r2 < 0.5) issues.push('局部模型 R² 仅 ' + d.r2.toFixed(2) + '，解释力偏弱');
  if (d.bad_sign && d.bad_sign.length) issues.push('部分因子系数方向与常识相反：' + d.bad_sign.slice(0, 2).join('、'));
  if (Math.abs(ue) / d.asking_price > 0.15) {
    issues.push('有 ' + Math.round(Math.abs(ue) / d.asking_price * 100) + '% 的价格无法被因素解释');
  }
  const lvl = issues.length === 0 ? '高' : (issues.length === 1 ? '中' : '低');
  const cls = issues.length === 0 ? 'ok' : (issues.length === 1 ? 'mid' : 'bad');
  $('dcQuality').innerHTML = '<span class="pill ' + cls + '">拆解可信度 ' + lvl + '</span>'
    + (issues.length
        ? '<ul class="qlist">' + issues.map(x => '<li>' + x + '</li>').join('') + '</ul>'
        : '<span class="muted small" style="margin-left:8px">样本量充足、解释力可接受</span>');

  $('dcTbl').querySelector('tbody').innerHTML = d.items.map(it => {
    const c = it.contribution;
    const cc = c > 1 ? 'ok' : (c < -1 ? 'bad' : 'muted');
    const off = DEC.pref[it.code] === 0 ? ' class="off"' : '';
    return '<tr' + off + '>'
      + '<td><input type="checkbox" data-dec="' + it.code + '"' + (DEC.pref[it.code] ? ' checked' : '') + '></td>'
      + '<td class="txt">' + it.name + (it.hint ? '<div class="hint2">' + it.hint + '</div>' : '') + '</td>'
      + '<td class="r ' + cc + '">' + (c >= 0 ? '+' : '') + price(c) + '</td>'
      + '<td class="r muted small">' + price(it.lo) + ' ~ ' + price(it.hi) + (it.significant ? '' : ' ?') + '</td>'
      + '</tr>';
  }).join('');

  $('dcTbl').querySelectorAll('input[data-dec]').forEach(cb => {
    cb.onchange = () => {
      DEC.pref[cb.dataset.dec] = cb.checked ? 1 : 0;
      cb.closest('tr').classList.toggle('off', !cb.checked);
      renderDecResult();
    };
  });

  renderDecResult();
}

function renderDecResult() {
  const d = DEC.data;
  if (!d) return;
  let adapted = d.base_price;
  const list = [];
  for (const it of d.items) {
    const w = DEC.pref[it.code] === 0 ? 0 : 1;
    adapted += w * it.contribution;
    if (!w && it.contribution > 0) list.push(it);
  }
  const area = 90;
  const anyOff = d.items.some(it => DEC.pref[it.code] === 0);
  // 全部勾选时，适配价严格等于市场价（避免逐项取整产生的 1-2 元误差）
  if (!anyOff) adapted = d.model_price;
  const diff = d.model_price - adapted;

  let html = '<div class="dec-row"><span>市场合理价</span><b>' + price(d.model_price) + ' 元/㎡</b></div>';
  html += '<div class="dec-row hl"><span>对你而言的适配价</span><b>' + price(adapted) + ' 元/㎡</b></div>';
  if (anyOff) {
    html += '<div class="dec-row"><span>' + (diff > 0 ? '你为不需要的东西多付' : '你占到的便宜') + '</span>'
      + '<b class="' + (diff > 0 ? 'bad' : 'ok') + '">' + price(Math.abs(diff)) + ' 元/㎡</b></div>';
    html += '<div class="dec-note">按 ' + area + ' ㎡ 折算：市场 '
      + NF.format(Math.round(d.model_price * area)) + ' 元　→　适配 '
      + NF.format(Math.round(adapted * area)) + ' 元　（差 '
      + NF.format(Math.round(Math.abs(diff) * area)) + ' 元）</div>';
    if (list.length) {
      html += '<div class="dec-note">冤枉钱：'
        + list.map(it => it.name + ' ' + price(it.contribution) + ' 元/㎡').join('、') + '</div>';
    }
  } else {
    html += '<div class="dec-note muted">勾掉你用不上的因素（比如有车不需要地铁），看适配价能降多少。</div>';
  }
  $('dcResult').innerHTML = html;
}

$('dcRun').onclick = rerunDecomp;
$('dcUseObs').onclick = () => { $('dcPrice').value = ''; rerunDecomp(); };

/* 支持 #decomp=<单元序号> 直接打开价格拆解（便于分享与截图） */
window.addEventListener('load', () => {
  const h = location.hash || '';
  if (!h.startsWith('#decomp')) return;
  const m = h.match(/^#decomp=(\d+)/);
  let idx = m ? parseInt(m[1], 10) : null;
  const go = () => {
    if (!S.boot) { setTimeout(go, 200); return; }
    if (idx == null) {
      const i = (S.boot.has_obs || []).findIndex(v => v);
      idx = i >= 0 ? i : 0;
    }
    S.unitIdx = idx;
    switchTab('decomp');
    showDecomp(idx);
    drawMap();
  };
  setTimeout(go, 800);
});
