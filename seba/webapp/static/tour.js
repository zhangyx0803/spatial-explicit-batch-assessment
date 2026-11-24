/* 新手引导：高亮 + 气泡，一步一步告诉用户先点什么 */
'use strict';

const TOUR_STEPS = [
  {
    sel: '#btnIntake', title: '第一步：接入你的数据',
    text: '点这里上传数据文件。系统会自动认出哪些是评估单元边界、哪些是路网、哪些是土地利用，并且自动识别每个字段的含义-你不需要改任何配置。',
    place: 'bottom',
  },
  {
    sel: '#itkDrop', title: '第二步：把文件拖进来',
    text: '支持 Shapefile（.shp 要连 .dbf 一起）、GeoJSON、KML、FileGDB、Excel 和 CSV。'
      + '评估单元边界是必需的，其余可以缺-缺哪类，对应的因子会自动停用。',
    place: 'bottom', before: () => { itkOpen(); },
  },
  {
    sel: '#itkResult', title: '第三步：核对自动识别结果',
    text: '每一类数据都会给出置信度。绿色表示很有把握，黄色要你看一眼，红色说明没找到这类数据。'
      + '字段映射的下拉框可以手动改，认错了直接换一个就行。',
    place: 'top', before: () => { itkSample(); },
  },
  {
    sel: '#itkApply', title: '第四步：确认，系统立刻出结果',
    text: '点这个按钮，配置会保存下来，并且马上用你的数据跑一遍-不用重启，不用改代码。',
    place: 'left',
  },
  {
    sel: '.stage', title: '第五步：看估值地图',
    text: '中间是估值分布图。颜色越深价格越高，图上的线是主干路，圆点是识别出来的各级商业中心地。'
      + '点任意一个地块，右侧会显示它的详细信息和价格构成。',
    place: 'right', before: () => { itkClose(); },
  },
  {
    sel: '.col.left', title: '第六步：换图层看不同结果',
    text: '显示图层可以切换看估值、残差、置信区间、各因子分布。'
      + '数据图层可以叠加地铁站、商业设施、学校等点位。',
    place: 'right',
  },
  {
    sel: '.tab[data-tab="factor"]', title: '第七步：调因子',
    text: '在因子设置里勾选或取消因子，右侧立刻重算。想看看去掉地铁会怎样？取消勾选就行。',
    place: 'left',
    before: () => { const t = document.querySelector('.tab[data-tab="factor"]'); if (t) t.click(); },
  },
  {
    sel: '#btnExport', title: '第八步：导出成果',
    text: '导出 Excel（含估值明细、因子长表、模型系数、共线性、精度对比、空间诊断）和残差专题图，可以直接放进报告。',
    place: 'left',
  },
];

const TOUR = { i: 0, on: false, raf: 0, el: null };

function tourStart(from = 0) {
  TOUR.on = true;
  TOUR.i = from;
  $('tourLayer').hidden = false;
  document.body.classList.add('touring');
  tourShow();
}

function tourEnd() {
  TOUR.on = false;
  TOUR.el = null;
  cancelAnimationFrame(TOUR.raf);
  $('tourLayer').hidden = true;
  document.body.classList.remove('touring');
  try { localStorage.setItem('seba_tour_done', '1'); } catch (e) {}
}

function tourShow() {
  const st = TOUR_STEPS[TOUR.i];
  if (!st) return tourEnd();

  if (st.before) { try { st.before(); } catch (e) {} }

  setTimeout(() => {
    let el = null;
    try { el = document.querySelector(st.sel); } catch (e) {}
    if (!el) { TOUR.i++; return tourShow(); }

    el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
    TOUR.el = el;
    tourSync();
    tourTrack();
    const r = el.getBoundingClientRect();
    const pad = 6;
    const ring = $('tourRing');
    ring.style.left = (r.left - pad) + 'px';
    ring.style.top = (r.top - pad) + 'px';
    ring.style.width = (r.width + pad * 2) + 'px';
    ring.style.height = (r.height + pad * 2) + 'px';

    $('tourStep').textContent = st.place === 'left' ? '' : '';
    $('tourTitle').textContent = st.title;
    $('tourText').textContent = st.text;
    $('tourIdx').textContent = `${TOUR.i + 1} / ${TOUR_STEPS.length}`;
    $('tourPrev').disabled = TOUR.i === 0;
    $('tourNext').textContent = TOUR.i === TOUR_STEPS.length - 1 ? '完成' : '下一步';

    const tip = $('tourTip');
    tip.hidden = false;
    const tw = tip.offsetWidth || 320;
    const th = tip.offsetHeight || 160;
    let left = r.right + 18;
    let top = r.top;
    if (st.place === 'left') left = r.left - tw - 18;
    if (st.place === 'bottom') { left = r.left; top = r.bottom + 16; }
    if (st.place === 'top') { left = r.left; top = r.top - th - 16; }
    left = Math.max(12, Math.min(window.innerWidth - tw - 12, left));
    top = Math.max(12, Math.min(window.innerHeight - th - 12, top));
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }, st.before ? 420 : 30);
}

/* 目标位置会变（项目名、计时器、数据加载都会重排），必须持续跟踪，
   否则高亮框会停在旧坐标上，看起来就是没对齐。 */
function tourTrack() {
  if (!TOUR.on) return;
  cancelAnimationFrame(TOUR.raf);
  let last = '';
  const tick = () => {
    if (!TOUR.on || !TOUR.el || !TOUR.el.isConnected) return;
    const r = TOUR.el.getBoundingClientRect();
    const key = [r.left, r.top, r.width, r.height].map(v => Math.round(v)).join(',');
    if (key !== last) { last = key; tourSync(); }
    TOUR.raf = requestAnimationFrame(tick);
  };
  TOUR.raf = requestAnimationFrame(tick);
}

function tourSync() {
  const el = TOUR.el;
  if (!el) return;
  const r = el.getBoundingClientRect();
  const pad = 6;
  const ring = $('tourRing');
  ring.style.left = (r.left - pad) + 'px';
  ring.style.top = (r.top - pad) + 'px';
  ring.style.width = (r.width + pad * 2) + 'px';
  ring.style.height = (r.height + pad * 2) + 'px';
}

function tourNext() {
  if (TOUR.i >= TOUR_STEPS.length - 1) return tourEnd();
  TOUR.i++; tourShow();
}

function tourPrev() {
  if (TOUR.i === 0) return;
  TOUR.i--; tourShow();
}

(function tourBind() {
  const b = $('btnTour');
  if (b) b.onclick = () => tourStart(0);
  const n = $('tourNext'); if (n) n.onclick = tourNext;
  const p = $('tourPrev'); if (p) p.onclick = tourPrev;
  const s = $('tourSkip'); if (s) s.onclick = tourEnd;
  document.addEventListener('keydown', e => {
    if (!TOUR.on) return;
    if (e.key === 'Escape') tourEnd();
    if (e.key === 'ArrowRight') tourNext();
    if (e.key === 'ArrowLeft') tourPrev();
  });
  window.addEventListener('resize', () => { if (TOUR.on) tourShow(); });

  // 首次进入自动引导；#tour 强制打开
  window.addEventListener('load', () => {
    if (location.hash === '#notour') return;
    if ((location.hash || '').indexOf('#decomp') === 0) return;
    if ((location.hash || '').indexOf('#scene') === 0 && location.hash !== '#scene=tour') return;
    if ((location.hash || '').indexOf('#d=') === 0) return;
    if (location.hash === '#tour') { setTimeout(() => tourStart(0), 300); return; }
    let done = null;
    try { done = localStorage.getItem('seba_tour_done'); } catch (e) {}
    const _noTour = new URLSearchParams(location.search).get('notour');
    if (!done && !_noTour && location.hash !== '#intake') setTimeout(() => tourStart(0), 900);
  });
})();
