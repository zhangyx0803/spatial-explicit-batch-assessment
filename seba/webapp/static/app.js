'use strict';

/* =========================================================================
   空间显式批量评估工作台系统 V1.0 —— 前端
   界面全中文；技术标识（英文代码）只在次要位置小字提示。
   ========================================================================= */

const S = {
  boot: null, result: null,
  field: 'est', fields: {}, geom: 'poly',
  selected: new Set(), unitIdx: null,
  busy: false, exported: null, t0: 0,
  openCard: null,
  layersOn: null,
  baseOn: null,
  centerOn: null,
};

const HELP = { el: null, timer: null };

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
const Q = (tip) => `<span class="q" data-tip="${tip}">?</span>`;

/* 因子名过长时，把括号里的说明整体放到第二行 */
function nameHtml(name) {
  const s = String(name || '');
  const i = s.indexOf('（');
  if (i <= 0) return `<span class="nm-main">${s}</span>`;
  return `<span class="nm-main">${s.slice(0, i)}</span><span class="nm-paren">${s.slice(i)}</span>`;
}

/* 中心地没有地铁名时，用最近的村/居委名兜底，避免出现无名点 */
function centerLabel(c) {
  if (c && c.name) return c.name;
  const u = S.boot && S.boot.units;
  if (!u || !u.x || !c) return '';
  let best = -1, bd = Infinity;
  for (let i = 0; i < u.x.length; i++) {
    const d = (u.x[i] - c.x) * (u.x[i] - c.x) + (u.y[i] - c.y) * (u.y[i] - c.y);
    if (d < bd) { bd = d; best = i; }
  }
  if (best < 0) return '';
  let txt = String(u.name[best] || '').replace(/居民委员会|居委会|村民委员会|村委会/g, '');
  if (txt.length > 10) txt = txt.slice(0, 10);
  return txt;
}

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

/* 问号提示：fixed 浮层，不会被卡片或滚动容器裁掉 */
function helpTipShow(target) {
  const tip = target && target.dataset ? target.dataset.tip : '';
  if (!tip) return;
  const el = $('helpTip');
  if (!el) return;
  HELP.el = target;
  el.textContent = tip;
  el.hidden = false;
  const r = target.getBoundingClientRect();
  const er = el.getBoundingClientRect();
  let x = r.left + r.width / 2 - er.width / 2;
  let y = r.bottom + 8;
  x = Math.max(8, Math.min(window.innerWidth - er.width - 8, x));
  if (y + er.height > window.innerHeight - 8) y = r.top - er.height - 8;
  el.style.left = x + 'px';
  el.style.top = Math.max(8, y) + 'px';
}
function helpTipHide() {
  const el = $('helpTip');
  if (el) el.hidden = true;
  HELP.el = null;
}
document.addEventListener('mouseover', (e) => {
  const t = e.target.closest && e.target.closest('[data-tip]');
  if (!t) return;
  clearTimeout(HELP.timer);
  HELP.timer = setTimeout(() => helpTipShow(t), 120);
});
document.addEventListener('mouseout', (e) => {
  const t = e.target.closest && e.target.closest('[data-tip]');
  if (!t) return;
  clearTimeout(HELP.timer);
  helpTipHide();
});
window.addEventListener('scroll', helpTipHide, true);
window.addEventListener('resize', helpTipHide);

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
  const cell = +S.boot.project.cell || 250;
  // 只显示本区地块的外接框 + 100 米缓冲。
  // 不能用 project.extent：那是连底图（邻区道路、水系、中心地）一起算的，
  // 崇明会因此把浦东也框进来。
  const polys = (S.boot.basemap || {}).unit_polys;
  if (polys && polys.length) {
    let a = 1e18, b = 1e18, c = -1e18, d = -1e18;
    for (const f of polys) {
      if (!f || f.length < 6) continue;
      for (let i = 0; i < f.length; i += 2) {
        if (f[i] < a) a = f[i];
        if (f[i] > c) c = f[i];
        if (f[i + 1] < b) b = f[i + 1];
        if (f[i + 1] > d) d = f[i + 1];
      }
    }
    if (c > a && d > b) return { x0: a - 100, y0: b - 100, x1: c + 100, y1: d + 100, cell };
  }
  const e = S.boot.project.extent;
  return { x0: e[0], y0: e[1], x1: e[2] + cell, y1: e[3] + cell, cell };
}

const VIEW = { k: 1, dx: 0, dy: 0 };
const TF = { s: 1, cx: 0, cy: 0, x0: 0, y1: 0 };

function X(x) { return TF.cx + (x - TF.x0) * TF.s; }
function Y(y) { return TF.cy - (y - TF.y1) * TF.s; }

function viewReset() { VIEW.k = 1; VIEW.dx = 0; VIEW.dy = 0; }

function layoutMap() {
  const cvs = $('map'), wrap = $('canvasWrap');
  const g = extentOf();
  const wData = Math.max(1, g.x1 - g.x0), hData = Math.max(1, g.y1 - g.y0);
  const availW = Math.max(160, wrap.clientWidth - 20);
  const availH = Math.max(160, wrap.clientHeight - 20);
  const dpr = window.devicePixelRatio || 1;

  // 画布固定为可用区域大小，缩放靠变换矩阵，不再改变画布尺寸
  cvs.style.width = availW + 'px';
  cvs.style.height = availH + 'px';
  cvs.width = Math.round(availW * dpr);
  cvs.height = Math.round(availH * dpr);

  const fit = Math.min(availW / wData, availH / hData);   // 适配比例
  const s = fit * VIEW.k;
  // 以“数据中心”为锚点，平移到画布中心，再叠加平移量
  TF.s = s;
  TF.x0 = (g.x0 + g.x1) / 2;
  TF.y1 = (g.y0 + g.y1) / 2;
  TF.cx = availW / 2 + VIEW.dx;
  TF.cy = availH / 2 + VIEW.dy;

  const ctx = cvs.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  Object.assign(MAP, { s, cell: g.cell, x0: g.x0, y0: g.y0, ctx, w: availW, h: availH });
  return { ctx, w: availW, h: availH, s, g };
}

function fieldPayload() {
  const a = S.result.arrays;
  switch (S.field) {
    case 'est': return { v: a.est_median, unit: '元/m²', div: false, price: true, title: '估值单价（中位口径）' };
    case 'est_cal': return { v: a.est_cal || a.est_median, unit: '元/m²', div: false, price: true, title: '校准后估值（按街道偏差修正）' };
    case 'actual': return { v: a.obs_price || [], unit: '元/m²', div: false, price: true, title: '实际挂牌单价（仅有价格的地块）' };
    case 'grade': return { v: (S.result.grades || []).map(g => g === 'ok' ? 1 : (g === 'warn' ? 0.5 : 0)), unit: '', div: false, title: '估值可信度（1=可直接用 0.5=建议复核 0=需人工）' };
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
  clampView();
  try { return drawMap0(); }
  catch (e) {
    console.error('drawMap', e);
    const t = document.getElementById('stageTitle');
    if (t) t.textContent = '绘图出错：' + e.message + ' || ' + String(e.stack||'').split('\n').slice(0,4).join(' >> ');
  }
}

/* 平移边界：1 倍时不能拖走；放大后最多把地图边缘拖到画布边缘 */
function clampView() {
  if (!S.boot) return;
  const wrap = $('canvasWrap');
  if (!wrap) return;
  const w = Math.max(160, wrap.clientWidth - 20);
  const h = Math.max(160, wrap.clientHeight - 20);
  const g = extentOf();
  const fit = Math.min(w / Math.max(1, g.x1 - g.x0), h / Math.max(1, g.y1 - g.y0));
  const s = fit * VIEW.k;
  // 判据：只要还有 1 个像素的内容落在画布上就允许，不再要求整幅图居中可见
  const cw = (g.x1 - g.x0) * s;
  const ch = (g.y1 - g.y0) * s;
  const maxDx = Math.max(0, cw / 2 + w / 2 - 1);
  const maxDy = Math.max(0, ch / 2 + h / 2 - 1);
  VIEW.dx = Math.max(-maxDx, Math.min(maxDx, VIEW.dx));
  VIEW.dy = Math.max(-maxDy, Math.min(maxDy, VIEW.dy));
}

function drawMap0() {
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
  if (MAP.bbox === undefined) buildBBox();

  // 按行政区边界裁剪：只画本区的东西，不让邻区干扰
  const clipPath = districtClipPath(bm, units);
  if (clipPath) { ctx.save(); ctx.clip(clipPath); }


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
    if (clipPath) { ctx.restore(); }
    drawWater(ctx, s, g);
    drawCenters(ctx, s, g);
    drawPoints(ctx, s, g);
    ctx.strokeStyle = '#aeb6bf';
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
    return;
  }

  for (let k = 0; k < units.x.length; k++) {
    const px = X(units.x[k]);
    const py = Y(units.y[k]);
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

  if (clipPath) { ctx.restore(); }
  drawWater(ctx, s, g);
  drawCenters(ctx, s, g);
  drawPoints(ctx, s, g);

  ctx.strokeStyle = '#aeb6bf';
  ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);

  if (S.unitIdx != null) {
    const polys = (S.boot.basemap || {}).unit_polys;
    const f = polys && polys[S.unitIdx];
    ctx.save();
    if (f && f.length >= 6) {
      ctx.beginPath();
      ctx.moveTo(X(f[0]), Y(f[1]));
      for (let i = 2; i < f.length; i += 2) ctx.lineTo(X(f[i]), Y(f[i + 1]));
      ctx.closePath();
      ctx.fillStyle = 'rgba(255, 236, 120, .45)';
      ctx.fill();
      ctx.strokeStyle = '#c9a227';
      ctx.lineWidth = 2;
      ctx.stroke();
    } else {
      const ux = X(units.x[S.unitIdx]), uy = Y(units.y[S.unitIdx]);
      ctx.beginPath();
      ctx.arc(ux, uy, Math.max(5, size * 0.7), 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 236, 120, .55)';
      ctx.fill();
      ctx.strokeStyle = '#c9a227';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    ctx.restore();
  }

  $('stageTitle').textContent = String(p.title || '').replace(/（[^）]*）/g, '');
  $('stageTitle').title = p.title || '';
  $('stageUnit').textContent = p.unit;
  const grad = p.div ? DIV : SEQ;
  $('legendBar').style.background = `linear-gradient(90deg,${grad.join(',')})`;
  $('legendScale').textContent = p.div
    ? `高估 ${brief(-hi)}　0　低估 ${brief(hi)}`
    : `最低 ${brief(lo)}　中位 ${brief(mid)}　最高 ${brief(hi)}${p.price ? ' 元/㎡' : ''}`;
  $('footLegend').hidden = !p.div;
  $('stageStat').textContent = '';
  const bmFoot = (S.boot.basemap || {});
  $('footInfo').textContent =
    `地块 ${S.boot.project.n_units} 个　道路 ${(bmFoot.roads || []).length} 段　`
    + `水体 ${(bmFoot.water || []).length} 处　中心地 ${(bmFoot.centers || []).length} 个　`
    + `参与建模的因子 ${S.result.features.length} 个`;
}

/* ---- 底图：路网 + 单元轮廓 ---- */
function drawBasemap(ctx, s, g) {
  const bm = (S.boot && S.boot.basemap) || {};

  if (!bm) return;

  // 全路网：细线叠加在色块上，既保留地理骨架又不压配色
  if ((!S.baseOn || S.baseOn.roads !== false) && bm.roads && bm.roads.length) {
    ctx.strokeStyle = 'rgba(74,86,100,.30)';
    ctx.lineWidth = Math.max(0.5, s * 5);
    ctx.lineCap = 'round';
    const _c1 = clipToDistrict(ctx);
    ctx.beginPath();
    for (const flat of bm.roads) {
      if (!flat || flat.length < 4) continue;
      ctx.moveTo(X(flat[0]), Y(flat[1]));
      for (let i = 2; i < flat.length; i += 2) ctx.lineTo(X(flat[i]), Y(flat[i + 1]));
    }
    ctx.stroke();
    if (_c1) ctx.restore();
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
}

/* 水体画在地块之上、且不裁剪到村界面：
   村界面是陆地地块的并集，河道往往恰好落在面与面之间，裁剪会把整条河裁没。 */
function drawWater(ctx, s, g) {
  const bm = (S.boot && S.boot.basemap) || {};
  if (S.baseOn && S.baseOn.water === false) return;
  if (!bm.water || !bm.water.length) return;
  ctx.save();
  ctx.fillStyle = '#cfe0ee';
  ctx.strokeStyle = '#a8c4dc';
  ctx.lineWidth = 0.6;
  const _c2 = clipToDistrict(ctx);
  ctx.beginPath();
  for (const flat of bm.water) {
    if (!flat || flat.length < 6) continue;
    ctx.moveTo(X(flat[0]), Y(flat[1]));
    for (let i = 2; i < flat.length; i += 2) ctx.lineTo(X(flat[i]), Y(flat[i + 1]));
    ctx.closePath();
  }
  ctx.fill();
  ctx.stroke();
  if (_c2) ctx.restore();
  ctx.restore();
}

/* 中心地：不裁剪到村界面，否则位于区界附近的市级/区级中心会被裁掉 */
function drawCenters(ctx, s, g) {
  const bm = (S.boot && S.boot.basemap) || {};
  if (!bm.centers || !bm.centers.length) return;
  if (S.centerOn && S.centerOn[1] === false && S.centerOn[2] === false && S.centerOn[3] === false) return;
  const col = { 1: '#7d2a1c', 2: '#a86f16', 3: '#2f5f7d' };
  for (const c of bm.centers) {
    if (S.centerOn && S.centerOn[c.level] === false) continue;
    const r = c.level === 1 ? 7 : (c.level === 2 ? 5 : 3.4);
    ctx.beginPath();
    ctx.arc(X(c.x), Y(c.y), r, 0, Math.PI * 2);
    ctx.fillStyle = col[c.level] || '#666';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.4;
    ctx.stroke();
    const txt = centerLabel(c);
    if (txt) {
      ctx.font = (c.level === 1 ? '600 10.5px' : '10px') + ' system-ui, sans-serif';
      ctx.fillStyle = 'rgba(32,36,40,.88)';
      ctx.strokeStyle = 'rgba(255,255,255,.95)';
      ctx.lineWidth = 2.6;
      ctx.strokeText(txt, X(c.x) + r + 3, Y(c.y) + 3);
      ctx.fillText(txt, X(c.x) + r + 3, Y(c.y) + 3);
    }
  }
}

/* 设施点图层：地铁 / 商业 / 公交 / 学校 等，按左侧图层勾选叠加 */
function drawPoints(ctx, s, g) {
  const bm = (S.boot && S.boot.basemap) || {};
  const groups = bm.points || [];
  if (!groups.length || !S.layersOn) return;
  const style = {
    poi_metro: { color: '#1f5f8b', r: 3.0, alpha: 1, shape: 'circle' },
    poi_shop: { color: '#b26a1f', r: 1.7, alpha: .62, shape: 'square' },
    poi_bus: { color: '#5f6b78', r: 1.2, alpha: .55, shape: 'circle' },
    poi_school: { color: '#2c6e4f', r: 2.0, alpha: .72, shape: 'triangle' },
    poi_cbd: { color: '#9e3b30', r: 3.8, alpha: 1, shape: 'diamond' },
  };
  const _c3 = clipToDistrict(ctx);
  for (const grp of groups) {
    if (!S.layersOn.has(grp.id)) continue;
    const st = style[grp.id] || { color: '#5f6b78', r: 1.3, alpha: .65, shape: 'circle' };
    ctx.save();
    ctx.globalAlpha = st.alpha;
    ctx.fillStyle = st.color;
    for (const p of (grp.xy || [])) {
      const px = X(p[0]), py = Y(p[1]), r = st.r;
      ctx.beginPath();
      if (st.shape === 'square') ctx.rect(px - r, py - r, r * 2, r * 2);
      else if (st.shape === 'triangle') {
        ctx.moveTo(px, py - r * 1.2);
        ctx.lineTo(px + r * 1.1, py + r * .8);
        ctx.lineTo(px - r * 1.1, py + r * .8);
        ctx.closePath();
      } else if (st.shape === 'diamond') {
        ctx.moveTo(px, py - r * 1.15);
        ctx.lineTo(px + r * 1.05, py);
        ctx.lineTo(px, py + r * 1.15);
        ctx.lineTo(px - r * 1.05, py);
        ctx.closePath();
      } else {
        ctx.arc(px, py, r, 0, Math.PI * 2);
      }
      ctx.fill();
    }
    ctx.restore();
  }
  if (_c3) ctx.restore();
}

function clipToDistrict(ctx) {
  const bm = (S.boot && S.boot.basemap) || {};
  const units = S.boot && S.boot.units;
  if (!units) return false;
  const p = districtClipPath(bm, units);
  if (!p) return false;
  ctx.save();
  ctx.clip(p);
  return true;
}

function districtClipPath(bm, units) {
  const polys = bm.unit_polys;
  if (!polys || !polys.length || polys.length !== units.x.length) return null;
  const p = new Path2D();
  for (const f of polys) {
    if (!f || f.length < 6) continue;
    p.moveTo(X(f[0]), Y(f[1]));
    for (let i = 2; i < f.length; i += 2) p.lineTo(X(f[i]), Y(f[i + 1]));
    p.closePath();
  }
  return p;
}

/* 预计算每个单元的包围盒（世界坐标），供命中测试快速过滤 */
function buildBBox() {
  const bm = (S.boot && S.boot.basemap) || {};
  const polys = bm.unit_polys;
  if (!polys || !polys.length || polys.length !== S.boot.units.x.length) {
    MAP.bbox = null;
    return;
  }
  MAP.bbox = polys.map((f) => {
    if (!f || f.length < 6) return null;
    let a = 1e18, b = 1e18, c = -1e18, d = -1e18;
    for (let i = 0; i < f.length; i += 2) {
      if (f[i] < a) a = f[i];
      if (f[i] > c) c = f[i];
      if (f[i + 1] < b) b = f[i + 1];
      if (f[i + 1] > d) d = f[i + 1];
    }
    return [a, b, c, d];
  });
}

function hitTest(ev) {
  if (!S.boot) return null;
  const rect = $('map').getBoundingClientRect();
  const px = ev.clientX - rect.left, py = ev.clientY - rect.top;
  // 屏幕 → 世界坐标（用当前视图变换的逆变换）
  const wx = TF.x0 + (px - TF.cx) / TF.s;
  const wy = TF.y1 - (py - TF.cy) / TF.s;
  const units = S.boot.units;
  const bm = (S.boot && S.boot.basemap) || {};
  const polys = bm.unit_polys;

  if (polys && MAP.bbox && polys.length === units.x.length) {
    for (let k = 0; k < polys.length; k++) {
      const bb = MAP.bbox[k];
      if (!bb) continue;
      if (wx < bb[0] || wx > bb[2] || wy < bb[1] || wy > bb[3]) continue;
      const f = polys[k];
      let inside = false;
      for (let i = 0, j = f.length - 2; i < f.length; i += 2) {
        const xi = f[i], yi = f[i + 1], xj = f[j], yj = f[j + 1];
        if (((yi > wy) !== (yj > wy)) && (wx < (xj - xi) * (wy - yi) / (yj - yi) + xi)) {
          inside = !inside;
        }
        j = i;
      }
      if (inside) return k;
    }
  }
  // 没有面数据（内置演示场景/六边形模式）：退回到最近质心，阈值随缩放自适应
  let best = null, bd = (22 / TF.s) ** 2;
  for (let k = 0; k < units.x.length; k++) {
    const dx = units.x[k] - wx, dy = units.y[k] - wy;
    const d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = k; }
  }
  return best;
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
    ['数据接入', `${NF.format(b.project.n_units)} 个地块 / ${NF.format(b.project.n_obs)} 个有价格`],
    ['因子计算', `${b.project.engine_factors} 个${b.project.cache_hits ? '（缓存复用 ' + b.project.cache_hits + '）' : '（内置结果）'}`],
    ['模型训练', r ? `解释度 ${(r.metrics.train.r2 * 100).toFixed(1)}%　${r.features.length} 个因子` : '—'],
    ['批量估值', r ? `${NF.format(b.project.n_units)} 个地块` : '—'],
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
  const builtin = p.source !== 'user';
  const rows = [
    ['评估单元', NF.format(p.n_units) + ' 个地块'],
    ['有价格', NF.format(p.n_obs) + ' 个地块'],
    ['单元尺寸', `${num(p.cell, 0)} 米`],
    ['地理底图', builtin ? '内置' : '我的数据'],
    ['价格来源', builtin ? '2024 小区挂牌价' : '我的数据'],
    ['坐标系', 'WGS84'],
    ['路网节点', n.n_nodes == null ? '—' : NF.format(n.n_nodes)],
    ['连通分量', n.n_components == null ? '—' : NF.format(n.n_components)],
    ['吸附失败率', n.snap_fail == null ? '—' : pct(n.snap_fail, 2)],
    ['平均吸附距离', n.snap_mean_dist == null ? '—' : `${num(n.snap_mean_dist, 0)} 米`],
    ['因子数量', `${NF.format(b.factors.length)} 个（参与建模 ${S.result.features.length} 个）`],
  ];
  $('metaList').innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');
  $('projName').textContent = p.source === 'user' ? (p.name || '我的数据') : '';
}

function renderFieldSelect() {
  const sel = $('fieldSel');
  const out = [
    ['est', '估值单价（中位口径）'],
    ['actual', '实际挂牌单价'],
    ['est_cal', '校准后估值'],
    ['grade', '估值可信度'],
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
  const bm = (S.boot && S.boot.basemap) || {};
  const pts = bm.points || [];
  if (!S.baseOn) S.baseOn = { roads: true, water: true };
  if (!S.centerOn) S.centerOn = { 1: true, 2: true, 3: true };
  const sym = { poi_metro: 'metro', poi_shop: 'shop', poi_bus: 'bus', poi_school: 'school', poi_cbd: 'cbd' };
  let html = '<div class="lgroup">底图</div>';
  html += `<div class="lrow">
    <label><input type="checkbox" data-base="roads" ${S.baseOn.roads !== false ? 'checked' : ''}>
    <i class="lsym road"></i><span class="id">道路网</span>
    <span class="ty">${NF.format((bm.roads || []).length)} 段</span></label></div>`;
  html += `<div class="lrow">
    <label><input type="checkbox" data-base="water" ${S.baseOn.water !== false ? 'checked' : ''}>
    <i class="lsym water"></i><span class="id">水体</span>
    <span class="ty">${NF.format((bm.water || []).length)} 处</span></label></div>`;
  html += '<div class="lgroup">设施点</div>';
  html += pts.map(p => {
    const on = S.layersOn ? S.layersOn.has(p.id) : true;
    return `<div class="lrow${on ? ' used' : ''}">
      <label><input type="checkbox" data-layer="${p.id}" ${on ? 'checked' : ''}>
      <i class="lsym ${sym[p.id] || 'bus'}"></i>
      <span class="id" title="${p.id}">${p.name}</span>
      <span class="ty">${NF.format((p.xy || []).length)}</span></label>
    </div>`;
  }).join('');
  $('layerList').innerHTML = html || '<div class="muted" style="padding:6px">暂无辅图层</div>';
  $('layerList').querySelectorAll('input[data-layer]').forEach(cb => {
    cb.onchange = () => {
      if (cb.checked) S.layersOn.add(cb.dataset.layer);
      else S.layersOn.delete(cb.dataset.layer);
      cb.closest('.lrow').classList.toggle('used', cb.checked);
      drawMap();
    };
  });
  $('layerList').querySelectorAll('input[data-base]').forEach(cb => {
    cb.onchange = () => {
      S.baseOn[cb.dataset.base] = cb.checked;
      cb.closest('.lrow').classList.toggle('used', cb.checked);
      drawMap();
    };
  });

  const centers = (bm.centers || []).slice().sort((a, b) => a.level - b.level);
  const lv = { 1: '市级中心地', 2: '区级中心地', 3: '社区级中心地' };
  const cl = $('centerList');
  if (cl) {
    cl.innerHTML = '<div class="lgroup">中心地（可单独显示）</div>' + [1, 2, 3].map(k => {
      const arr = centers.filter(c => c.level === k);
      const names = arr.map(centerLabel).filter(Boolean);
      const on = S.centerOn[k] !== false;
      return `<div class="lrow${on ? ' used' : ''}">
        <label><input type="checkbox" data-center="${k}" ${on ? 'checked' : ''} ${arr.length ? '' : 'disabled'}>
        <i class="lsym c${k}"></i><span class="id">${lv[k]}</span>
        <span class="ty">${arr.length} 个</span></label>
        ${names.length ? `<div class="lsub">${names.join('、')}</div>` : ''}
      </div>`;
    }).join('');
    cl.querySelectorAll('input[data-center]').forEach(cb => {
      cb.onchange = () => {
        S.centerOn[+cb.dataset.center] = cb.checked;
        cb.closest('.lrow').classList.toggle('used', cb.checked);
        drawMap();
      };
    });
  }
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
    ['拟合度 R²（训练）' + Q('模型能解释的价格差异比例。0.80 表示地块之间 80% 的价格差异可由模型里的地理因素解释；训练值通常偏乐观。'), raw(m.train.r2, 3), m.train.r2 >= .85 ? 'ok' : 'mid'],
    ['拟合度 R²（空间留块）' + Q('把一整片区域留出后再预测，更接近真实外推能力。通常会低于训练 R²，差距越大说明模型越依赖局部样本。'), raw(m.cv_spatial.r2, 3), m.cv_spatial.r2 >= .85 ? 'ok' : 'mid'],
    ['平均误差 MAPE' + Q('预测值与实际值的平均绝对百分比误差，越低越好。'), raw(m.cv_spatial.mape, 1) + '%', m.cv_spatial.mape <= 20 ? 'ok' : 'bad'],
    ['离散系数 COD' + Q('IAAO 比率检验指标，衡量估值是否集中一致。住宅通常宜小于 15，越小越好。'), raw(r.ratio.cod, 1), codOk ? 'ok' : 'bad'],
    ['价格相关差 PRD' + Q('估值是否随价格水平系统性偏离。宜在 0.98–1.03 之间，接近 1 为好。'), raw(r.ratio.prd, 3), prdOk ? 'ok' : 'bad'],
    ['残差空间自相关' + Q('Moran\'s I，检验残差是否在空间上聚集。接近 0 表示误差随机；p<0.05 且 I>0 表示成片高估或低估，说明还有地理因素没进模型。'), raw(r.moran.i, 3), moranOk ? 'ok' : 'bad'],
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
      <span class="code" style="font-family:inherit;font-size:11px">${nameHtml(f.name)}</span>
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
    return `<tr><td class="txt">${nameHtml(name)}</td><td class="r">${coef}</td><td class="r">${t}</td>
            <td class="r ${star ? 'sig' : 'ns'}" title="p = ${p}">${star || '—'}</td></tr>`;
  }).join('');
}

function renderVif() {
  $('vifTbl').querySelector('tbody').innerHTML = S.result.vif.slice(0, 6).map(([n, r2, v]) => {
    const cls = v > 10 ? 'hi' : (v > 5 ? 'sig' : '');
    return `<tr><td class="txt">${n}</td><td class="r ${cls}">${v.toFixed(2)}</td></tr>`;
  }).join('');
}

function renderDiag() {
  renderCalib();
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
    $('uId').textContent = u.unit_name || u.unit_id;
    const _useTxt = u.use_detail || (u.use_type === '住宅' ? '住宅' : '非住宅');
    $('uAdmin').innerHTML =
      `<span class="kv"><i>用途</i><b>${_useTxt}</b></span>`
      + `<span class="kv"><i>所属街道</i><b>${u.admin || '—'}</b></span>`
      + `<span class="kv"><i>占地面积</i><b>${num(u.area, 0)} ㎡</b></span>`;

    const gTxt = { ok: '可直接用', warn: '建议复核', bad: '需人工核', unknown: '—' }[u.grade] || '—';
    const gCls = { ok: 'ok', warn: 'mid', bad: 'bad' }[u.grade] || 'mid';
    const nonres = u.use_type && u.use_type !== '住宅';
    if (nonres) {
      $('uMetrics').innerHTML = `<div class="mrow" style="grid-column:span 2">
        <span class="k">本单元是否有价</span><span class="v mid" style="font-size:11px">否</span></div>
        <div class="mrow" style="grid-column:span 2">
        <span class="k" style="color:#8d959f">这里是${_useTxt}用地，不是住宅，
        因此不参与估值与精度统计。</span></div>`;
      // 非住宅没有价格，因子取值对使用者没有意义，整表与标题一起隐藏
      const _t = $('uFactorTbl');
      _t.style.display = 'none';
      _t.querySelector('tbody').innerHTML = '';
      const _tt = $('uFactorTitle'); if (_tt) _tt.style.display = 'none';
      return;
    }
    $('uFactorTbl').style.display = '';
    const _tt2 = $('uFactorTitle'); if (_tt2) _tt2.style.display = '';
    const items = [
      ['估值单价（中位）', price(u.est_median) + ' 元/㎡', 'mid'],
      ['校准后估值', u.est_cal != null ? price(u.est_cal) + ' 元/㎡' : '—', 'mid'],
      ['本单元可信度' + Q('按所在街道的样本量与偏差分级：可直接用 = 样本≥12 且偏差≤8%；建议复核 = 样本≥6 且偏差≤20%；需人工核 = 样本不足或偏差过大。'), gTxt, gCls],
      ['估值单价（均值）', price(u.est_mean) + ' 元/㎡', 'mid'],
      ['价格下限 P10', price(u.p_low) + ' 元/㎡', 'mid'],
      ['价格上限 P90', price(u.p_high) + ' 元/㎡', 'mid'],
      ['残差' + Q('实际价格与模型估计的对数差。正数表示模型低估，负数表示模型高估；只有有价格的地块才有残差。'), u.resid == null ? '本单元无价格' : raw(u.resid, 3),
        u.resid == null ? 'mid' : (u.resid > 0 ? 'bad' : 'ok')],
      ['实际价格', u.obs ? price(u.obs.sale_unit_price) + ' 元/㎡' : '—', 'mid'],
    ];
    $('uMetrics').innerHTML = items.map(([k, v, c]) =>
      `<div class="mrow" style="grid-column:span 2"><span class="k">${k}</span>
        <span class="v ${c}" style="font-size:11px">${v}</span></div>`).join('');

    $('uFactorTbl').querySelector('tbody').innerHTML = u.factors.map(f => `
      <tr><td class="txt">${nameHtml(f.name)}</td><td class="r">${brief(f.value)}</td>
      <td class="r ${f.selected ? 'sig' : 'ns'}">${f.selected ? '✓' : ''}</td></tr>`).join('');
  } catch (e) { toast(e.message, true); }
}

/* =========================================================================
   右栏：因子设置
   ========================================================================= */
function renderFactorCards() {
  const box = $('factorCards');
  const valid = (S.boot.factors || []).filter(f => !f.invalid);
  const card = (f) => {
    const open = S.openCard === f.code;
    return `<div class="fcard${f.selected ? '' : ' off'}" data-code="${f.code}">
      <div class="fcard-h" data-toggle="${f.code}">
        <input type="checkbox" data-en="${f.code}" ${f.selected ? 'checked' : ''} title="${f.selected ? '参与建模' : '未参与；勾选后加入模型'}">
        <span class="nm">${nameHtml(f.name)}</span>
        <span class="op">${f.selected ? f.op_name : '未参与'}</span>
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
  };
  // 本区恒定、无法估计的因子直接不展示，避免“淡色但还能勾选”的误解。
  box.innerHTML = valid.map(card).join('') || '<div class="muted" style="padding:8px">本区没有可用因子</div>';
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
  const pts = (payload.basemap && payload.basemap.points) || [];
  // 默认只叠交通类点，商业/学校点量大，按需勾选，避免把价格色块盖住
  S.layersOn = new Set(pts.filter(p => !['poi_shop', 'poi_school'].includes(p.id)).map(p => p.id));
  S.baseOn = { roads: true, water: true };
  S.centerOn = { 1: true, 2: true, 3: true };
  viewReset();
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
      <input class="input name" data-lname="${i}" value="${ly.name}" placeholder="给这份图层起个名字，如“学校”">
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
  if (!IMP.units) { toast('请先选择“评估单元”文件', true); return; }
  if (!IMP.obs) { toast('请先选择“成交记录”文件', true); return; }
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
    if (b.need_select) {
      await showPicker(b.districts || [], b.current);
      return;
    }
    adopt(b);
    syncDistrictName(b.district || b.project && b.project.name || '');
    initDistrictSelect(b.district || b.current || '');
    const q = new URLSearchParams(location.search);
    const tab = q.get('tab');
    if (tab === 'diag') {
      switchTab('model');
      _openDiag();
    } else if (tab && ['model', 'unit', 'factor', 'decomp'].includes(tab)) switchTab(tab);
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
  if (!S.result || DRAG.on) { $('tip').hidden = true; return; }
  const k = hitTest(ev);
  if (k === null) { $('tip').hidden = true; return; }
  const p = fieldPayload();
  const v = (p.v || [])[k];
  const nm = (S.boot.units.name && S.boot.units.name[k]) || S.boot.units.id[k];
  const ut = (S.boot.units.use_type || [])[k];
  const ud = (S.boot.units.use_detail || [])[k] || '非住宅';
  if (ut && ut !== '住宅') {
    showTip(ev, `${nm}（${ud}）：不估值`);
    return;
  }
  const _a = (S.result && S.result.arrays) || {};
  const op = (_a.obs_price || [])[k];
  const est = (_a.est_median || [])[k];
  if (op !== null && op !== undefined) {
    showTip(ev, `${nm} ｜ ${price(op)} 元/㎡（挂牌）`);
    return;
  }
  showTip(ev, (est === null || est === undefined) ? `${nm} ｜ 无价格、无估值`
    : `${nm} ｜ ${price(est)} 元/㎡（估值）`);
});
$('map').addEventListener('mouseleave', () => { $('tip').hidden = true; });
$('map').addEventListener('click', (ev) => {
  if (DRAG.moved) { DRAG.moved = false; return; }   // 拖拽结束不当作点击
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
  ['model', 'unit', 'factor', 'decomp'].forEach(n => { $('tab-' + n).hidden = (n !== name); });
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

const _openDiag = () => {
  if (!S.result) { toast('请先选择一个区'); return; }
  renderDiag();
  $('diagModal').hidden = false;
};
$('btnDiag').onclick = _openDiag;
$('diagClose').onclick = () => { $('diagModal').hidden = true; };
$('diagModal').onclick = (ev) => { if (ev.target.id === 'diagModal') $('diagModal').hidden = true; };

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
const pint = (v) => NF.format(Math.round(v || 0));

async function showDecomp(idx) {
  if (idx == null) return;
  DEC.idx = idx;
  $('decompEmpty').hidden = true;
  $('decompBody').hidden = false;
  $('dcTbl').querySelector('tbody').innerHTML =
    '<tr><td colspan="3" class="muted" style="padding:14px">正在拆解……（首次约 1–3 秒）</td></tr>';
  try {
    const d = await postJSON('/api/decompose', { i: idx, price: null, radius: 1500, min_n: 120 });
    DEC.data = d;
    DEC.pref = {};
    // 50% = 市场平均支付意愿；100% = 双倍看重；0% = 不认可；负值 = 反向折价。
    d.items.forEach(it => { DEC.pref[it.code] = 0.5; });
    renderDecomp();
  } catch (e) {
    $('dcTbl').querySelector('tbody').innerHTML =
      '<tr><td colspan="3" class="bad" style="padding:14px">' + e.message + '</td></tr>';
  }
}

async function rerunDecomp() {
  if (DEC.idx == null) return;
  const p = parseFloat($('dcPrice').value) || null;
  $('dcTbl').querySelector('tbody').innerHTML =
    '<tr><td colspan="3" class="muted" style="padding:14px">正在按新价格重新拆解……</td></tr>';
  try {
    const d = await postJSON('/api/decompose', { i: DEC.idx, price: p, radius: 1500, min_n: 120 });
    DEC.data = d;
    d.items.forEach(it => { if (!(it.code in DEC.pref)) DEC.pref[it.code] = 0.5; });
    renderDecomp();
  } catch (e) { toast(e.message, true); }
}

function renderDecomp() {
  const d = DEC.data;
  if (!d) return;
  if (d.blocked) {
    $('dcUnit').textContent = d.unit_name || '';
    $('dcMeta').textContent = '　非住宅用地';
    $('dcBase').textContent = '—';
    $('dcModel').textContent = '—';
    $('dcUnexp').textContent = '—';
    $('dcSample').textContent = '—';
    $('dcPrice').value = '';
    $('dcQuality').innerHTML = '';
    $('dcResult').innerHTML = '';
    $('dcTbl').querySelector('tbody').innerHTML =
      '<tr><td colspan="3" class="muted" style="padding:18px 12px">' + d.reason + '</td></tr>';
    return;
  }
  $('dcUnit').textContent = (d.unit_name || d.unit_id);
  $('dcUnit').title = d.unit_id;
  $('dcMeta').textContent = '　局部拟合：周边 ' + Math.round(d.radius) + ' 米　' + d.n_samples + ' 个价格样本　局部解释度 ' + Math.round(d.r2 * 100) + '%';
  $('dcPrice').value = Math.round(d.asking_price);
  $('dcBase').textContent = price(d.base_price);
  $('dcModel').textContent = price(d.model_price);
  const ue = d.unexplained;
  const ueCls = Math.abs(ue) / d.asking_price > 0.15 ? 'warn' : '';
  $('dcUnexp').innerHTML = '<span class="' + ueCls + '">' + (ue >= 0 ? '+' : '') + price(ue) + '</span>';
  $('dcSample').textContent = d.n_samples + ' 套';

  const issues = [];
  if (d.n_samples < 100) issues.push('价格样本仅 ' + d.n_samples + ' 个，系数估计不稳');
  if (d.r2 < 0.5) issues.push('局部模型解释度仅 ' + Math.round(d.r2 * 100) + '%，解释力偏弱');
  if (d.bad_sign && d.bad_sign.length) issues.push('部分因子系数方向与常识相反：' + d.bad_sign.slice(0, 2).join('、'));
  const uep = Math.abs(ue) / d.asking_price * 100;
  if (uep > 15) {
    issues.push('本例中 ' + Math.round(uep) + '% 的价格找不到因素依据（见下方说明）');
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
    const w = Math.round((DEC.pref[it.code] == null ? 0.5 : DEC.pref[it.code]) * 100);
    const off = w <= 0 ? ' class="off"' : '';
    return '<tr' + off + '>'
      + '<td class="wcell"><input type="range" min="0" max="100" step="10" value="' + w
      + '" data-dec="' + it.code + '"><b>' + w + '%</b></td>'
      + '<td class="txt">' + it.name + (it.hint ? '<div class="hint2">' + it.hint + '</div>' : '') + '</td>'
      + '<td class="r"><div class="' + cc + '">' + (c >= 0 ? '+' : '') + pint(c) + '</div>'
      + '<div class="civ ' + (it.significant ? '' : 'ns') + '">'
      + pint(it.lo) + '~' + pint(it.hi) + (it.significant ? '' : '?') + '</div></td>'
      + '</tr>';
  }).join('');

  $('dcTbl').querySelectorAll('input[data-dec]').forEach(sl => {
    sl.oninput = () => {
      const v = parseInt(sl.value, 10) / 100;
      DEC.pref[sl.dataset.dec] = v;
      const pw = Math.round(v * 100);
      sl.parentNode.querySelector('b').textContent = pw + '%';
      sl.closest('tr').classList.toggle('off', pw <= 0);
      renderDecResult();
    };
  });

  renderDecResult();
}

function renderDecResult() {
  const d = DEC.data;
  if (!d || !d.items) return;
  let adapted = d.base_price;
  const cut = [];
  for (const it of d.items) {
    const pref = DEC.pref[it.code] == null ? 0.5 : DEC.pref[it.code];
    // 50% 是市场平均支付意愿，对应原来的权重 1；100% 为双倍，0% 为不认可。
    const w = pref * 2;
    adapted += w * it.contribution;
    if (Math.abs(w - 1) > 1e-9) cut.push({ name: it.name, gap: (1 - w) * it.contribution, w: w });
  }
  const anyOff = cut.length > 0;
  if (!anyOff) adapted = d.model_price;
  const diff = d.model_price - adapted;
  const pct = d.model_price ? Math.round(Math.abs(diff) / d.model_price * 100) : 0;

  let html = '<div class="dec-row"><span>市场平均价</span><b>' + price(d.model_price) + ' 元/㎡</b></div>';
  html += '<div class="dec-row hl"><span>按你的支付意愿</span><b>' + price(adapted) + ' 元/㎡</b></div>';
  if (anyOff) {
    if (diff > 0) {
      html += '<div class="dec-row"><span>两者差额</span><b>' + price(diff) + ' 元/㎡（占市场价 ' + pct + '%）</b></div>';
      html += '<div class="dec-note">差额来自你调低的支付意愿：这些价值在市场上存在，但对你个人不构成同等价值。</div>';
      const pos = cut.filter(x => x.gap > 1);
      if (pos.length) {
        html += pos.map(x => '<div class="dec-row sub"><span>' + x.name
          + '</span><b>' + price(x.gap) + ' 元/㎡</b></div>').join('');
      }
    } else {
      html += '<div class="dec-row"><span>两者差额</span><b>+' + price(-diff) + ' 元/㎡（占市场价 ' + pct + '%）</b></div>';
      html += '<div class="dec-note">按你的支付意愿，这套房对你的价值高于市场平均价。</div>';
    }
  } else {
    html += '<div class="dec-note muted">各项均为 50%（市场平均）时，适配价与市场平均价相同。调整滑杆即可看到差异。</div>';
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

/* =========================================================================
   场景深链：#scene=xxx  —— 用于说明书截图，可稳定复现每个步骤的界面状态
   ========================================================================= */
const SCENES = {
  home:      {},                                              // 初始地图
  hex:       { geom: 'hex' },                                 // 六边形网格
  dot:       { geom: 'dot' },                                 // 质心点
  resid:     { field: 'resid' },                              // 残差图层
  unit:      { unit: 246, tab: 'unit' },                      // 单元详情
  decomp:    { unit: 246, tab: 'decomp' },                    // 价格拆解
  decomp2:   { unit: 246, tab: 'decomp', prefs: { rt_metro_time: 0 } },   // 有车：不付地铁钱
  decomp3:   { unit: 246, tab: 'decomp',
               prefs: { rt_metro_time: 0, rt_shop_1km: 0 } },          // 有车 + 不喜欢商场
  decomp4:   { unit: 246, tab: 'decomp', price: 150000 },                 // 议价：业主挂牌
  pick:      { probe: true },
  hover:     { probe: true, quiet: true },
  parkunit:  { unitName: '大宁灵石公园', tab: 'unit' },
  parkhover: { hoverUnit: '大宁灵石公园' },
  resthover: { hoverUnit: '大宁路505弄居委' },
  zoom:      { zoom: 2.6 },
  diag:      { tab: 'model', diag: true },                    // 全区空间诊断（估值模型页内折叠区）
  factor:    { tab: 'factor' },                               // 因子设置
  intake:    { modal: 'intake' },                             // 数据接入向导
  import:    { modal: 'import' },                             // 导入表格
};

function runScene() {
  try {
  const _q = new URLSearchParams(location.search);
  const _m = (location.hash || '').match(/#scene=([a-z0-9_]+)/i)
    || (_q.get('scene') ? [null, _q.get('scene')] : null);
  const m = _m;
  if (!m) return;
  const sc = SCENES[m[1].toLowerCase()];
  if (!sc) return;
  // 数据还没就绪：稍后重试（选区流程也会走到这里）
  if (!S.boot) { setTimeout(runScene, 350); return; }

  const go = () => {
    if (!S.boot) { setTimeout(go, 200); return; }
    if (sc.geom) {
      S.geom = sc.geom;
      document.querySelectorAll('#geomSeg .segbtn').forEach(b =>
        b.classList.toggle('active', b.dataset.geom === sc.geom));
    }
    if (sc.field) {
      const sel = $('fieldSel');
      if (sel) { sel.value = sc.field; sel.onchange && sel.onchange(); }
    }
    if (sc.hoverUnit) {
      const _hi = (S.boot.units.name || []).indexOf(sc.hoverUnit);
      if (_hi >= 0) {
        const cv = document.getElementById('map');
        const rr = cv.getBoundingClientRect();
        cv.dispatchEvent(new MouseEvent('mousemove', {
          clientX: rr.left + X(S.boot.units.x[_hi]),
          clientY: rr.top + Y(S.boot.units.y[_hi]),
          bubbles: true
        }));
      }
    }
    if (sc.unitName) {
      const _i = (S.boot.units.name || []).indexOf(sc.unitName);
      if (_i >= 0) sc.unit = _i;
    }
    if (sc.unit != null) {
      S.unitIdx = sc.unit;
      if (sc.tab === 'unit') { switchTab('unit'); showUnit(sc.unit); }
      if (sc.tab === 'decomp') { switchTab('decomp'); }
    } else if (sc.tab) {
      switchTab(sc.tab);
    }
    if (sc.diag) { _openDiag(); }
    if (typeof drawMap === 'function') { drawMap(); }
    if (sc.zoom) { VIEW.k = sc.zoom; drawMap(); syncZoomLabel(); }
    if (sc.probe) {
      const cv = document.getElementById('map');
      const r = cv.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const hit = hitTest({ clientX: cx, clientY: cy });
      const t = document.getElementById('stageTitle');
      if (t && !sc.quiet) t.textContent = '悬停命中测试：中心点 → '
        + (hit === null ? '未命中' : S.boot.units.id[hit] + '（索引 ' + hit + '）');
      const tip = document.getElementById('tip');
      if (hit !== null && tip) {
        const p2 = fieldPayload();
        const v = (p2.v || [])[hit];
        tip.textContent = (S.boot.units.name && S.boot.units.name[hit]) || S.boot.units.id[hit];
        tip.hidden = false;
        tip.style.left = (r.width / 2) + 'px';
        tip.style.top = (r.height / 2) + 'px';
        tip.style.transform = 'translate(-50%,-128%)';
      }
    }
    if (sc.unit != null && sc.tab === 'decomp' && sc.price) {
      const setp = (tries) => {
        const el = document.getElementById('dcPrice');
        if (!el || !DEC.data) { if (tries < 60) setTimeout(() => setp(tries + 1), 150); return; }
        el.value = sc.price;
        rerunDecomp();
      };
      setTimeout(() => setp(0), 200);
    }
    if (sc.unit != null && sc.tab === 'decomp' && sc.prefs) {
      const apply = (tries) => {
        if (!DEC.data || !DEC.data.items) {
          if (tries < 60) { setTimeout(() => apply(tries + 1), 150); }
          return;
        }
        const tbl = $('dcTbl');
        Object.entries(sc.prefs).forEach(([code, v]) => {
          DEC.pref[code] = v;
          const sl = tbl.querySelector('input[data-dec="' + code + '"]');
          if (sl) {
            sl.value = Math.round(v * 100);
            const pw = Math.round(v * 100);
            const b = sl.parentNode.querySelector('b');
            if (b) b.textContent = pw + '%';
            sl.closest('tr').classList.toggle('off', pw <= 0);
          }
        });
        renderDecResult();
      };
      setTimeout(() => apply(0), 200);
    }
    if (sc.modal === 'intake') { setTimeout(() => { itkOpen(); itkSample(); }, 500); }
    if (sc.modal === 'import') { setTimeout(() => { $('importModal').hidden = false; }, 400); }
  };
  setTimeout(go, 900);
  } catch (e) { console.warn("scene error", e); }
}

runScene();

/* =========================================================================
   画布交互：滚轮缩放 / 拖拽平移 / 双击复位
   ========================================================================= */
const DRAG = { on: false, x: 0, y: 0, moved: false };

(function wireCanvas() {
  const cv = $('map');

  cv.addEventListener('wheel', (ev) => {
    if (!S.boot) return;
    ev.preventDefault();
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const k0 = VIEW.k;
    const k1 = Math.min(12, Math.max(0.5, k0 * (ev.deltaY < 0 ? 1.2 : 1 / 1.2)));
    if (k1 === k0) return;
    // 保持光标下的地理点在缩放前后不动
    const cx0 = rect.width / 2 + VIEW.dx, cy0 = rect.height / 2 + VIEW.dy;
    const r = k1 / k0;
    const cx1 = mx - (mx - cx0) * r;
    const cy1 = my - (my - cy0) * r;
    VIEW.dx = cx1 - rect.width / 2;
    VIEW.dy = cy1 - rect.height / 2;
    VIEW.k = k1;
    drawMap();
    syncZoomLabel();
  }, { passive: false });

  cv.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    DRAG.on = true; DRAG.moved = false;
    DRAG.x = ev.clientX; DRAG.y = ev.clientY;
    cv.style.cursor = 'grabbing';
  });

  window.addEventListener('mousemove', (ev) => {
    if (!DRAG.on) return;
    const dx = ev.clientX - DRAG.x, dy = ev.clientY - DRAG.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) DRAG.moved = true;
    VIEW.dx += dx; VIEW.dy += dy;
    DRAG.x = ev.clientX; DRAG.y = ev.clientY;
    drawMap();
  });

  window.addEventListener('mouseup', () => {
    if (!DRAG.on) return;
    DRAG.on = false;
    cv.style.cursor = '';
  });

  cv.addEventListener('dblclick', () => { viewReset(); drawMap(); syncZoomLabel(); });
})();

function syncZoomLabel() {
  const el = $('zoomLbl');
  if (el) el.textContent = VIEW.k === 1 ? '1×' : VIEW.k.toFixed(1) + '×';
}

$('btnZoomReset') && ($('btnZoomReset').onclick = () => {
  viewReset(); drawMap(); syncZoomLabel();
});

/* =========================================================================
   进入时先选行政区
   ========================================================================= */
async function showPicker(list, current) {
  const wrap = $('pickWrap');
  wrap.hidden = false;
  const grid = $('pickGrid');
  grid.innerHTML = list.map(d => `
    <button class="pickcard" data-name="${d.name}">
      <b>${d.name}${d.name === current ? ' ✓' : ''}</b>
      <span>${d.units ? NF.format(d.units) + ' 个地块' : ''}${d.obs ? '　' + NF.format(d.obs) + ' 个有价格' : ''}</span>
      <span class="${d.r2 >= 0.85 ? 'r2' : ''}">${d.r2 != null ? '模型解释度 ' + (d.r2 * 100).toFixed(1) + '%' : (d.mb ? d.mb + ' MB' : '')}</span>
    </button>`).join('');
  // #d=奉贤区 直接选中的深链
  const dm = (location.hash || '').match(/^#d=([^&]+)/);
  if (dm) {
    const want = decodeURIComponent(dm[1]);
    const hit = grid.querySelector('[data-name="' + want + '"]');
    if (hit) { setTimeout(() => hit.click(), 120); }
  }
  grid.querySelectorAll('.pickcard').forEach(btn => {
    btn.onclick = async () => {
      const name = btn.dataset.name;
      grid.querySelectorAll('.pickcard').forEach(b => b.classList.add('loading'));
      btn.querySelector('span').textContent = '正在加载……';
      try {
        const b2 = await postJSON('/api/district', { name });
        wrap.hidden = true;
        adopt(b2);
        syncDistrictName(name);
        initDistrictSelect(name);
        const _q = new URLSearchParams(location.search);
        const _u = _q.get('unit');
        if (_u !== null && _u !== '' && !Number.isNaN(+_u)) {
          const _tab = _q.get('tab');
          if (_tab === 'decomp') { switchTab('decomp'); showDecomp(+_u); }
          else { switchTab('unit'); showUnit(+_u); }
        }
        if (window.__afterAdopt) { window.__afterAdopt(); window.__afterAdopt = null; }
      } catch (e) {
        toast('加载失败：' + e.message, true);
        grid.querySelectorAll('.pickcard').forEach(b => b.classList.remove('loading'));
      }
    };
  });
}

function syncDistrictName(name) {
  const el = $('districtSel');
  if (!el) return;
  if (name) el.value = name;
  el.hidden = !(el.options && el.options.length);
  const lab = $('districtLabel');
  if (lab) lab.hidden = el.hidden;
}

async function initDistrictSelect(current) {
  const sel = $('districtSel');
  if (!sel) return;
  try {
    const r = await getJSON('/api/districts');
    const list = r.districts || [];
    if (!list.length) { sel.hidden = true; $('districtLabel').hidden = true; return; }
    sel.innerHTML = list.map(d => `<option value="${d.name}">${d.name}</option>`).join('');
    sel.value = current || r.current || list[0].name;
    sel.hidden = false;
    $('districtLabel').hidden = false;
    sel.onchange = async () => {
      const name = sel.value;
      if (!name || name === (S.boot && S.boot.district)) return;
      sel.disabled = true;
      try {
        setBusy(true);
        const b = await postJSON('/api/district', { name });
        adopt(b);
        syncDistrictName(name);
      } catch (e) { toast('切换失败：' + e.message, true); }
      finally { sel.disabled = false; setBusy(false); }
    };
  } catch (e) { sel.hidden = true; }
}

function renderCalib() {
  const tb = document.querySelector('#calibTbl tbody');
  if (!tb) return;
  const cal = (S.result && S.result.calibration) || null;
  if (!cal || !cal.groups || !cal.groups.length) {
    tb.innerHTML = '<tr><td colspan="5" class="muted">暂无校准数据</td></tr>';
    return;
  }
  const tag = { ok: ['可直接用', 'ok'], warn: ['建议复核', 'mid'], bad: ['需人工核', 'bad'] };
  tb.innerHTML = cal.groups.slice(0, 20).map(g => {
    const t = tag[g.grade] || ['—', 'mid'];
    const pct = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
    return '<tr><td class="txt">' + g.name + '</td>'
      + '<td class="r">' + g.n + '</td>'
      + '<td class="r">' + pct(g.raw) + '</td>'
      + '<td class="r">' + pct(g.bias) + '</td>'
      + '<td class="r ' + t[1] + '">' + t[0] + '</td></tr>';
  }).join('');
}

