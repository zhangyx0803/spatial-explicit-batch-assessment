# -*- coding: utf-8 -*-
"""把评估结果导出成单个 HTML 文件——双击就能看，不需要 Python、不需要服务器。

用法：
    .venv\\Scripts\\python.exe make_static_html.py
    .venv\\Scripts\\python.exe make_static_html.py --bundle data/demo_xuhui.bundle --out 结果.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = os.path.dirname(os.path.abspath(__file__))

BASE_FIELDS = [
    ("est_median", "估值单价（中位口径）", "money", False),
    ("est_mean", "估值单价（均值口径）", "money", False),
    ("p_low", "区间下限 P10", "money", False),
    ("p_high", "区间上限 P90", "money", False),
    ("resid", "残差（对数）", "plain", True),
]


def build_payload(bundle: str) -> dict:
    from seba.webapp.state import AppState

    cfg = os.path.join(HERE, "config", "factors_real.yaml")
    st = AppState(cfg, dataset=None, prebuilt=True) if False else None

    from seba.bundle import load_bundle

    ds, notes, extra = load_bundle(bundle)
    st = AppState(cfg, dataset=ds, notes=notes, source="bundle", prebuilt=True)

    boot = st.bootstrap()
    fields = {}
    for code, label, kind, div in BASE_FIELDS:
        arr = (boot.get("result") or {}).get("arrays", {}).get(code)
        if arr:
            fields[code] = {"name": label, "kind": kind, "div": div, "values": arr}

    for f in boot.get("factors") or []:
        code = f["code"]
        if code in ds.attrs:
            try:
                d = st.field(code)
                fields[code] = {"name": d["name"], "kind": "plain", "div": False,
                                "values": d["values"]}
            except Exception:
                continue

    return {"boot": boot, "fields": fields,
            "built": __import__("time").strftime("%Y-%m-%d %H:%M")}


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{font:13px/1.5 "Microsoft YaHei","PingFang SC","Helvetica Neue",Arial,sans-serif;
  color:#1a1e24;background:#eceef1;display:flex;flex-direction:column}
.appbar{height:44px;flex:0 0 44px;background:#222a33;color:#dfe4ea;display:flex;align-items:center;
  gap:12px;padding:0 14px}
.appbar .mark{font-weight:700;letter-spacing:.06em;font-size:12px;color:#fff;
  background:#1f4e5f;padding:3px 8px;border-radius:3px}
.appbar b{font-size:13px;color:#fff;font-weight:600}
.appbar .v{font-size:10px;color:#8d959f;border:1px solid #3a434d;padding:0 4px;border-radius:2px}
.appbar .proj{color:#98a2ad;font-size:11.5px}
.appbar .grow{flex:1}
.appbar .tag{font-size:11px;color:#9fb3c8;border:1px solid #3a434d;padding:2px 7px;border-radius:2px}
main{flex:1;display:grid;grid-template-columns:236px 1fr 400px;gap:10px;padding:10px;min-height:0}
.col{display:flex;flex-direction:column;gap:10px;min-height:0;overflow:auto}
.card{background:#fff;border:1px solid #d7dade;border-radius:3px}
.card h2{margin:0;padding:7px 10px;font-size:11.5px;font-weight:600;color:#5d656f;
  border-bottom:1px solid #e6e9ec;background:#fafbfc}
.card .pad{padding:8px 10px}
table{width:100%;border-collapse:collapse;font-size:12px}
.kv td{padding:3px 0}
.kv td:first-child{color:#7a828c;width:88px}
.kv td:last-child{text-align:right;font-family:Consolas,Monaco,monospace;font-variant-numeric:tabular-nums}
.tbl th{font-size:11px;color:#7a828c;font-weight:500;text-align:left;padding:4px 6px;
  border-bottom:1px solid #e6e9ec;background:#fafbfc;position:sticky;top:0}
.tbl td{padding:4px 6px;border-bottom:1px solid #f0f2f4;font-family:Consolas,Monaco,monospace;
  font-variant-numeric:tabular-nums;font-size:11.5px}
.tbl td:first-child{font-family:inherit;color:#2b3138}
.num{text-align:right}
.select,input{width:100%;height:28px;border:1px solid #cfd5dc;border-radius:3px;
  padding:0 6px;font:inherit;font-size:12px;background:#fff;color:inherit}
.seg{display:flex;margin-top:8px;border:1px solid #d7dade;border-radius:3px;overflow:hidden}
.segbtn{flex:1;padding:5px 0;font-size:11.5px;cursor:pointer;background:#fff;color:#5d656f;
  border:0;border-right:1px solid #d7dade;font:inherit}
.segbtn:last-child{border-right:0}
.segbtn.active{background:#1f4e5f;color:#fff}
.hint{color:#8d959f;font-size:11px;margin:6px 0 0;line-height:1.6}
.stage{background:#fff;border:1px solid #d7dade;border-radius:3px;display:flex;
  flex-direction:column;min-height:0;overflow:hidden}
.stage-head{height:34px;flex:0 0 34px;display:flex;align-items:center;gap:10px;padding:0 12px;
  border-bottom:1px solid #e6e9ec;font-size:12.5px}
.stage-head b{font-weight:600}
.stage-head .muted{color:#8d959f;font-size:11px;margin-left:auto;
  font-family:Consolas,Monaco,monospace}
#cv{flex:1;display:block;min-height:0;cursor:crosshair}
.stage-foot{height:34px;flex:0 0 34px;display:flex;align-items:center;gap:10px;padding:0 12px;
  border-top:1px solid #e6e9ec;font-size:11px;color:#7a828c}
#ramp{width:120px;height:9px;border:1px solid #d7dade;border-radius:1px}
.legend{display:flex;align-items:center;gap:4px}
.cdot{display:inline-block;width:8px;height:8px;border-radius:50%;border:1px solid #fff;margin-left:6px}
.cdot.l1{background:#7d2a1c}.cdot.l2{background:#a86f16}.cdot.l3{background:#2f5f7d}
.mono{font-family:Consolas,Monaco,monospace;font-variant-numeric:tabular-nums}
.big{font-size:15px;font-weight:600}
.ok{color:#2f6b46}.bad{color:#8a3b2c}
.pill{font-size:10.5px;padding:1px 5px;border-radius:2px;background:#eef0f3;color:#6a727c}
.pill.ok{background:#e3efe6;color:#2f6b46}
.pill.bad{background:#f2e3e0;color:#8a3b2c}
.detail-empty{color:#8d959f;font-size:12px;padding:14px 4px;text-align:center}
.note{font-size:11px;color:#7a828c;line-height:1.7;padding:6px 10px;border-left:2px solid #d7dade;
  background:#fafbfc;margin:0 8px 8px}
</style>
</head>
<body>
<header class="appbar">
  <div class="mark">SEBA</div>
  <div><b>空间显式批量评估工作台</b> <span class="v">V1.0</span></div>
  <div class="proj" id="projName"></div>
  <div class="grow"></div>
  <div class="tag">离线网页版 · 生成于 __BUILT__</div>
</header>

<main>
  <!-- 左栏 -->
  <aside class="col">
    <section class="card">
      <h2>工程概况</h2>
      <div class="pad"><table class="kv" id="projInfo"></table></div>
    </section>
    <section class="card">
      <h2>显示图层</h2>
      <div class="pad">
        <select id="fieldSel" class="select"></select>
        <div class="seg" id="geomSeg">
          <button class="segbtn active" data-geom="poly">村居面</button>
          <button class="segbtn" data-geom="hex">六边形</button>
          <button class="segbtn" data-geom="dot">质心点</button>
        </div>
        <p class="hint">点地图上任意地块查看明细</p>
      </div>
    </section>
    <section class="card">
      <h2>参与建模的因子</h2>
      <div class="pad" style="padding:0"><table class="tbl" id="factorTbl"></table></div>
    </section>
  </aside>

  <!-- 地图 -->
  <section class="stage">
    <div class="stage-head">
      <b id="mapTitle">估值单价</b>
      <span id="mapSub"></span>
      <span class="muted" id="mapStats"></span>
    </div>
    <canvas id="cv"></canvas>
    <div class="stage-foot">
      <div id="ramp"></div>
      <span id="rampLabels" class="mono"></span>
      <span class="grow" style="flex:1"></span>
      <span class="legend">
        <i class="cdot l1"></i>市级中心地
        <i class="cdot l2"></i>区级
        <i class="cdot l3"></i>社区级
      </span>
      <span id="footInfo"></span>
    </div>
  </section>

  <!-- 右栏 -->
  <aside class="col">
    <section class="card">
      <h2>精度指标</h2>
      <div class="pad"><table class="kv" id="metricTbl"></table></div>
    </section>
    <section class="card" id="detailCard" hidden>
      <h2>单元详情</h2>
      <div class="pad" id="detailBody"></div>
    </section>
    <section class="card">
      <h2>模型系数（对数尺度，正为提价）</h2>
      <div class="pad" style="padding:0"><table class="tbl" id="coefTbl"></table></div>
    </section>
    <section class="card">
      <h2>共线性</h2>
      <div class="pad" style="padding:0"><table class="tbl" id="vifTbl"></table></div>
    </section>
    <section class="card">
      <h2>空间诊断</h2>
      <div class="pad" id="diagBody"></div>
    </section>
  </aside>
</main>

<script>
const DATA = __PAYLOAD__;
const B = DATA.boot, F = DATA.fields;
const U = B.units, P = B.project, R = B.result, BM = B.basemap || {};
const S = { field: 'est_median', geom: 'poly', sel: null };

/* ---------- 颜色 ---------- */
const SEQ = ['#fdf6ec','#fbe3c4','#f6c68c','#eda05c','#d97544','#b04a34','#7a2a22'];
const DIV = ['#21618c','#7fb0cc','#eef1f4','#d9a08f','#a3382b'];
function hex2rgb(h){return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)]}
function ramp(stops,t){
  t=Math.max(0,Math.min(1,t));
  const n=stops.length-1,x=t*n,i=Math.min(Math.floor(x),n-1),f=x-i;
  const a=hex2rgb(stops[i]),b=hex2rgb(stops[i+1]);
  return `rgb(${Math.round(a[0]+(b[0]-a[0])*f)},${Math.round(a[1]+(b[1]-a[1])*f)},${Math.round(a[2]+(b[2]-a[2])*f)})`;
}
const NF = new Intl.NumberFormat('zh-CN');
function money(v){ return v==null?'—':NF.format(Math.round(v)); }
function brief(v){ return v==null?'—':(Math.abs(v)>=100?NF.format(Math.round(v)):v.toFixed(2)); }

/* ---------- 画布 ---------- */
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
let GEO = null;
function layout(){
  const r = cv.getBoundingClientRect();
  const dpr = window.devicePixelRatio||1;
  cv.width = Math.max(1,Math.round(r.width*dpr));
  cv.height = Math.max(1,Math.round(r.height*dpr));
  ctx.setTransform(dpr,0,0,dpr,0,0);
  const w=r.width,h=r.height;
  const e=P.extent;
  const dataW=e[2]-e[0]||1, dataH=e[3]-e[1]||1;
  const pad=10;
  const s=Math.min((w-pad*2)/dataW,(h-pad*2)/dataH);
  const ox=(w-dataW*s)/2, oy=(h-dataH*s)/2;
  return {w,h,s,ox,oy,x0:e[0],x1:e[2],y0:e[1],y1:e[3],cell:P.cell||100};
}
function X(x){return GEO.ox+(x-GEO.x0)*GEO.s}
function Y(y){return GEO.oy+(GEO.y1-y)*GEO.s}

function hexRound(q,r){
  let x=q,z=r,y=-x-z;
  let rx=Math.round(x),ry=Math.round(y),rz=Math.round(z);
  const dx=Math.abs(rx-x),dy=Math.abs(ry-y),dz=Math.abs(rz-z);
  if(dx>dy&&dx>dz)rx=-ry-rz; else if(dy>dz)ry=-rx-rz; else rz=-rx-ry;
  return [rx,rz];
}
function draw(){
  GEO = layout();
  const {w,h} = GEO;
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle='#fff'; ctx.fillRect(0,0,w,h);

  const F1 = F[S.field] || F['est_median'];
  const vals = F1.values;
  const sorted = vals.filter(v=>Number.isFinite(v)).slice().sort((a,b)=>a-b);
  const nv = sorted.length;
  const at = q => nv?sorted[Math.min(nv-1,Math.max(0,Math.floor((nv-1)*q)))]:0;
  const lo=at(0.02), hi=at(0.98);
  const rankT = x => { let a=0,b=nv-1; while(a<=b){const m=(a+b)>>1; if(sorted[m]<x)a=m+1;else b=m-1;} return nv>1?a/(nv-1):0.5; };

  // 水体
  if(BM.water && BM.water.length){
    ctx.fillStyle='#dce8f2'; ctx.beginPath();
    for(const f of BM.water){ if(!f||f.length<6)continue; ctx.moveTo(X(f[0]),Y(f[1]));
      for(let i=2;i<f.length;i+=2)ctx.lineTo(X(f[i]),Y(f[i+1])); ctx.closePath(); }
    ctx.fill();
  }

  const usePoly = BM.unit_polys && BM.unit_polys.length===U.x.length;
  const mode = S.geom==='poly'&&!usePoly ? 'dot' : S.geom;

  if(mode==='hex'){
    const spanX=GEO.x1-GEO.x0, spanY=GEO.y1-GEO.y0;
    const Rr=Math.max(150,Math.min(1200,Math.max(spanX,spanY)/46));
    const wq=Math.sqrt(3)*Rr, buckets=new Map();
    for(let k=0;k<U.x.length;k++){
      const v=vals[k]; if(!Number.isFinite(v))continue;
      const q=U.x[k]/wq-(U.y[k]/(1.5*Rr))/2, r=U.y[k]/(1.5*Rr);
      const [hq,hr]=hexRound(q,r), key=hq+','+hr;
      let b=buckets.get(key); if(!b){b={q:hq,r:hr,sw:0,sv:0};buckets.set(key,b);}
      const wt=U.area?U.area[k]:1; b.sw+=wt; b.sv+=v*wt;
    }
    for(const b of buckets.values()){
      const v=b.sv/(b.sw||1);
      const cx=GEO.ox+(wq*(b.q+b.r/2)-GEO.x0)*GEO.s;
      const cy=GEO.oy+(GEO.y1-1.5*Rr*b.r)*GEO.s;
      const rr=Rr*GEO.s;
      ctx.beginPath();
      for(let i=0;i<6;i++){
        const a=Math.PI/180*(60*i+30);
        const px=cx+rr*Math.cos(a), py=cy+rr*Math.sin(a);
        i?ctx.lineTo(px,py):ctx.moveTo(px,py);
      }
      ctx.closePath();
      ctx.fillStyle = F1.div ? ramp(DIV,0.5+0.5*Math.sign(v)*rankT(Math.abs(v))) : ramp(SEQ,rankT(v));
      ctx.fill(); ctx.strokeStyle='rgba(255,255,255,.55)'; ctx.lineWidth=.5; ctx.stroke();
    }
  } else {
    for(let k=0;k<U.x.length;k++){
      const v=vals[k];
      const col = (v==null||!Number.isFinite(v)) ? '#eef0f3'
        : (F1.div ? ramp(DIV,0.5+0.5*Math.sign(v)*rankT(Math.abs(v))) : ramp(SEQ,rankT(v)));
      if(mode==='poly'){
        const f=BM.unit_polys[k];
        if(f&&f.length>=6){
          ctx.beginPath(); ctx.moveTo(X(f[0]),Y(f[1]));
          for(let i=2;i<f.length;i+=2)ctx.lineTo(X(f[i]),Y(f[i+1]));
          ctx.closePath(); ctx.fillStyle=col; ctx.fill(); continue;
        }
      }
      const sz=Math.max(1.5,GEO.cell*GEO.s);
      ctx.fillStyle=col;
      ctx.fillRect(X(U.x[k])-sz/2,Y(U.y[k])-sz/2,Math.ceil(sz),Math.ceil(sz));
    }
  }

  // 路网
  if(BM.roads && BM.roads.length){
    ctx.strokeStyle='rgba(74,86,100,.30)'; ctx.lineWidth=Math.max(.5,GEO.s*5); ctx.lineCap='round';
    ctx.beginPath();
    for(const f of BM.roads){ if(!f||f.length<4)continue; ctx.moveTo(X(f[0]),Y(f[1]));
      for(let i=2;i<f.length;i+=2)ctx.lineTo(X(f[i]),Y(f[i+1])); }
    ctx.stroke();
  }
  // 单元轮廓
  if(mode==='poly'&&BM.unit_polys&&BM.unit_polys.length){
    ctx.strokeStyle='rgba(255,255,255,.28)'; ctx.lineWidth=.6; ctx.beginPath();
    for(const f of BM.unit_polys){ if(!f||f.length<6)continue; ctx.moveTo(X(f[0]),Y(f[1]));
      for(let i=2;i<f.length;i+=2)ctx.lineTo(X(f[i]),Y(f[i+1])); ctx.closePath(); }
    ctx.stroke();
  }
  // 中心地
  if(BM.centers){
    const col={1:'#7d2a1c',2:'#a86f16',3:'#2f5f7d'};
    for(const c of BM.centers){
      const r=c.level===1?5.5:(c.level===2?4:2.6);
      ctx.beginPath(); ctx.arc(X(c.x),Y(c.y),r,0,Math.PI*2);
      ctx.fillStyle=col[c.level]||'#666'; ctx.fill();
      ctx.strokeStyle='#fff'; ctx.lineWidth=1.2; ctx.stroke();
    }
  }
  // 选中高亮
  if(S.sel!=null && mode!=='hex'){
    const f = usePoly ? BM.unit_polys[S.sel] : null;
    ctx.strokeStyle='#11161c'; ctx.lineWidth=2.2;
    if(f&&f.length>=6){
      ctx.beginPath(); ctx.moveTo(X(f[0]),Y(f[1]));
      for(let i=2;i<f.length;i+=2)ctx.lineTo(X(f[i]),Y(f[i+1]));
      ctx.closePath(); ctx.stroke();
    } else {
      const sz=Math.max(8,GEO.cell*GEO.s);
      ctx.strokeRect(X(U.x[S.sel])-sz/2,Y(U.y[S.sel])-sz/2,sz,sz);
    }
  }

  // 图例
  const g=ctx.createLinearGradient(0,0,120,0);
  const stops = F1.div?DIV:SEQ;
  stops.forEach((c,i)=>g.addColorStop(i/(stops.length-1),c));
  const rampEl=document.getElementById('ramp');
  rampEl.style.background=`linear-gradient(90deg,${stops.join(',')})`;
  document.getElementById('rampLabels').textContent =
    (F1.kind==='money'?money(lo):brief(lo))+' → '+(F1.kind==='money'?money(hi):brief(hi));
  document.getElementById('mapStats').textContent =
    `单元 ${U.x.length}　中位 ${F1.kind==='money'?money(at(.5)):brief(at(.5))}`;
}

/* ---------- 表格 ---------- */
function kv(el, rows){
  el.innerHTML = rows.map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}
function build(){
  document.getElementById('projName').textContent = P.name || '';
  document.title = (P.name||'评估结果') + ' · 空间显式批量评估工作台';
  document.getElementById('mapTitle').textContent = F[S.field]?.name || '';

  kv(document.getElementById('projInfo'), [
    ['评估单元', NF.format(P.n_units)],
    ['成交样本', NF.format(P.n_obs)],
    ['单元尺寸', (P.cell||0)+' 米'],
    ['路网节点', NF.format((B.network||{}).n_nodes||0)],
    ['吸附失败率', ((B.network||{}).snap_fail*100||0).toFixed(2)+'%'],
    ['因子数量', (B.factors||[]).length],
  ]);

  const m = R.metrics||{}, tr=m.train||{}, cvr=m.cv_random||{}, cvs=m.cv_spatial||{};
  const rt = R.ratio||{}, mo = R.moran||{};
  const cod = rt.cod, prd = rt.prd;
  const codOk = cod != null && cod <= (rt.cod_max||15);
  const prdOk = prd != null && prd >= (rt.prd_low||0.98) && prd <= (rt.prd_high||1.03);
  kv(document.getElementById('metricTbl'), [
    ['训练 R²', `<span class="big ok">${(tr.r2||0).toFixed(3)}</span>`],
    ['空间块 CV R²', `<span class="big">${(cvs.r2||0).toFixed(3)}</span>`],
    ['随机 CV R²', (cvr.r2||0).toFixed(3)],
    ['MAPE', ((tr.mape||0)).toFixed(1)+'%'],
    ['离散系数 COD', `${cod==null?'—':cod.toFixed(1)} <span class="pill ${codOk?'ok':'bad'}">${codOk?'达标':'超限'}</span>`],
    ['价格相关差 PRD', `${prd==null?'—':prd.toFixed(3)} <span class="pill ${prdOk?'ok':'bad'}">${prdOk?'达标':'超限'}</span>`],
    ['中位比率', (rt.median_ratio||0).toFixed(3)],
    ["Moran's I", (mo.i||0).toFixed(3)],
  ]);

  const sel = new Set((R.features)||[]);
  document.getElementById('factorTbl').innerHTML =
    '<tr><th>因子</th><th class="num">均值</th></tr>' +
    (B.factors||[]).filter(f=>sel.has(f.code)).map(f=>
      `<tr><td>${f.name}</td><td class="num">${Number(f.mean).toFixed(3)}</td></tr>`).join('');

  const selEl = document.getElementById('fieldSel');
  selEl.innerHTML = Object.entries(F).map(([k,v])=>
    `<option value="${k}"${k===S.field?' selected':''}>${v.name}</option>`).join('');
  selEl.onchange = ()=>{ S.field=selEl.value;
    document.getElementById('mapTitle').textContent = F[S.field].name; draw(); };

  document.getElementById('coefTbl').innerHTML =
    '<tr><th>变量</th><th class="num">系数</th><th class="num">t</th><th class="num">p</th></tr>' +
    (R.coef||[]).map(c=>{
      const pv = parseFloat(c[4]);
      const stars = c[5] || (pv<.001?'***':pv<.01?'**':pv<.05?'*':'');
      return `<tr><td>${c[0]}</td><td class="num">${c[1]}</td>
        <td class="num">${c[3]}</td><td class="num">${c[4]} ${stars}</td></tr>`;
    }).join('');

  document.getElementById('vifTbl').innerHTML =
    '<tr><th>变量</th><th class="num">VIF</th></tr>' +
    (R.vif||[]).map(v=>`<tr><td>${v[0]}</td><td class="num">${Number(v[2]).toFixed(2)}</td></tr>`).join('');

  const I = mo.i ?? 0, pv = mo.p ?? 1;
  document.getElementById('diagBody').innerHTML =
    `<table class="kv">
       <tr><td>Moran's I</td><td>${I.toFixed(3)}</td></tr>
       <tr><td>z 值</td><td>${(mo.z||0).toFixed(2)}</td></tr>
       <tr><td>p 值</td><td>${pv.toFixed(4)}</td></tr>
       <tr><td>置换次数</td><td>${mo.n_perm||0}</td></tr>
     </table>
     <div class="note">${mo.verdict || (I>0.2&&pv<0.05
        ? '残差存在显著正空间自相关：全局模型假设不成立，建议转局部模型。'
        : '残差空间自相关不显著，全局模型可接受。')}</div>`;

  document.getElementById('footInfo').textContent =
    `道路 ${(BM.roads||[]).length} · 水体 ${(BM.water||[]).length} · 中心地 ${(BM.centers||[]).length}`;
}

/* ---------- 交互 ---------- */
function pick(ev){
  const r = cv.getBoundingClientRect();
  const px = ev.clientX-r.left, py = ev.clientY-r.top;
  let best=-1, bd=1e18;
  const limit = Math.max(25, GEO.cell*GEO.s*1.2);
  for(let k=0;k<U.x.length;k++){
    const dx = X(U.x[k])-px, dy = Y(U.y[k])-py;
    const d = dx*dx+dy*dy;
    if(d<bd){bd=d;best=k;}
  }
  if(best<0 || bd>limit*limit) return;
  S.sel = best; draw(); showDetail(best);
}
function showDetail(k){
  const card=document.getElementById('detailCard'), body=document.getElementById('detailBody');
  card.hidden=false;
  const base=(R.arrays||{});
  const rows=[];
  rows.push(['单元编号', U.id[k]]);
  rows.push(['所属街道', U.admin?U.admin[k]:'—']);
  rows.push(['面积', NF.format(Math.round(U.area?U.area[k]:0))+' ㎡']);
  rows.push(['坐标', `${Math.round(U.x[k])}, ${Math.round(U.y[k])}`]);
  rows.push(['有成交', B.has_obs&&B.has_obs[k]?'是':'否']);
  rows.push(['估值中位', base.est_median?money(base.est_median[k]):'—']);
  rows.push(['区间', base.p_low?`${money(base.p_low[k])} ~ ${money(base.p_high[k])}`:'—']);
  if(base.resid) rows.push(['残差', Number(base.resid[k]).toFixed(4)]);

  let html = '<table class="kv">'+rows.map(([a,b])=>`<tr><td>${a}</td><td>${b}</td></tr>`).join('')+'</table>';
  html += '<div style="margin-top:8px;font-size:11px;color:#7a828c">全部因子取值</div>';
  html += '<table class="tbl">'+Object.entries(F).filter(([c])=>!['est_median','est_mean','p_low','p_high','resid'].includes(c))
    .map(([c,v])=>`<tr><td>${v.name}</td><td class="num">${Number(v.values[k]).toFixed(3)}</td></tr>`).join('')+'</table>';
  body.innerHTML = html;
}

document.getElementById('geomSeg').querySelectorAll('.segbtn').forEach(b=>{
  b.onclick=()=>{
    document.getElementById('geomSeg').querySelectorAll('.segbtn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active'); S.geom=b.dataset.geom; draw();
  };
});
cv.addEventListener('click', pick);
window.addEventListener('resize', draw);
build(); draw();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=os.path.join(HERE, "data", "demo_xuhui.bundle"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not os.path.exists(args.bundle):
        print("找不到数据包：%s" % args.bundle)
        return 2

    print("正在读取数据包并构造结果 …")
    payload = build_payload(args.bundle)

    title = (payload["boot"].get("project") or {}).get("name") or "评估结果"
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = (HTML_TEMPLATE
            .replace("__TITLE__", title + " · 离线网页版")
            .replace("__BUILT__", payload["built"])
            .replace("__PAYLOAD__", blob))

    safe = "".join(c for c in title if c.isalnum() or c in " _-()（）")
    safe = "_".join(safe.split()) or "评估结果"
    out = args.out or os.path.join(HERE, "dist_static", safe + "_网页版.html")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("已生成：%s" % out)
    print("大小：%.2f MB（单文件，双击即可在浏览器打开）" % (os.path.getsize(out) / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
