# -*- coding: utf-8 -*-
"""把评估结果导出成单个 HTML 文件-双击就能看，不需要 Python、不需要服务器。

用法：
    .venv\\Scripts\\python.exe make_static_html.py
    .venv\\Scripts\\python.exe make_static_html.py --bundle data/xuhui.bundle --out 结果.html
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
    ("obs_price", "实际挂牌单价", "money", False),
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

    # --- 预计算每个有成交单元的局部拆解 ---
    print("  预计算价格拆解（%d 个单元）..." % len(ds.obs.unit_idx))
    from seba.decompose import BUYER_HINT, decompose

    decs = {}
    feats = [c for c in (boot.get("result") or {}).get("features", []) if c in ds.attrs]
    w = {c: 1.0 for c in feats}
    t0 = __import__("time").time()
    for n, i in enumerate(sorted(set(int(x) for x in ds.obs.unit_idx))):
        try:
            d = decompose(ds, w, i, radius=1500.0, min_n=120, n_boot=120)
        except Exception:
            continue
        decs[str(i)] = {
            "unit_id": d.unit_id,
            "ask": round(d.asking_price),
            "base": round(d.base_price),
            "model": round(d.model_price),
            "unexplained": round(d.unexplained),
            "n": d.n_samples,
            "radius": round(d.radius),
            "r2": round(d.r2, 3),
            "bad_sign": d.bad_sign,
            "items": [{
                "code": it.code, "name": it.name,
                "hint": BUYER_HINT.get(it.code, ""),
                "c": round(float(it.contribution)),
                "lo": round(float(it.lo)), "hi": round(float(it.hi)),
                "sig": not (it.lo <= 0 <= it.hi),
            } for it in d.items],
        }
        if (n + 1) % 50 == 0:
            print("    %d / %d ..." % (n + 1, len(set(int(x) for x in ds.obs.unit_idx))))
    print("  拆解完成，用时 %.0f 秒，共 %d 个" % (__import__("time").time() - t0, len(decs)))

    return {"boot": boot, "fields": fields, "decomps": decs,
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
.appbar .brand{display:flex;flex-direction:column;justify-content:center;gap:1px;white-space:nowrap}
.appbar .brand-en{font:500 7.5px/1.1 Consolas,Monaco,monospace;letter-spacing:.16em;
  text-transform:uppercase;color:#93a0aa}
.appbar .brand-cn{font-size:13px;color:#fff;font-weight:600;letter-spacing:.3px}
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
.stage-foot{min-height:34px;flex:0 0 auto;display:flex;align-items:center;flex-wrap:wrap;gap:4px 10px;padding:3px 12px;
  border-top:1px solid #e6e9ec;font-size:11px;color:#7a828c}
#ramp{width:120px;height:9px;border:1px solid #d7dade;border-radius:1px}
#footInfo{white-space:normal}
.legend{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.cdot{display:inline-block;width:8px;height:8px;border-radius:50%;border:1px solid #fff;margin-left:6px}
.cdot.l1{background:#7d2a1c}.cdot.l2{background:#a86f16}.cdot.l3{background:#2f5f7d}
.mono{font-family:Consolas,Monaco,monospace;font-variant-numeric:tabular-nums}
.big{font-size:15px;font-weight:600}
.ok{color:#2f6b46}.bad{color:#8a3b2c}
.pill{font-size:10.5px;padding:1px 5px;border-radius:2px;background:#eef0f3;color:#6a727c}
.pill.ok{background:#e3efe6;color:#2f6b46}
.pill.bad{background:#f2e3e0;color:#8a3b2c}
.detail-empty{color:#8d959f;font-size:12px;padding:14px 4px;text-align:center}
.dec-sum{display:grid;grid-template-columns:1fr 1fr;gap:3px 12px;font-size:11.5px;margin-bottom:8px}
.dec-sum>div{display:flex;justify-content:space-between}
.dec-sum .k{color:#7a828c}
.dec-sum .v{font-family:Consolas,Monaco,monospace;font-variant-numeric:tabular-nums}
.dec-q{font-size:11px;color:#7a828c;line-height:1.7;margin-bottom:8px;
  padding:5px 8px;background:#fafbfc;border-left:2px solid #d7dade}
.dec-tbl2{width:100%;border-collapse:collapse;font-size:11.5px}
.dec-tbl2 td{padding:4px 3px;border-bottom:1px solid #f0f2f4;vertical-align:top}
.dec-tbl2 .wc{width:62px;white-space:nowrap}
.dec-tbl2 .wc input[type=range]{width:38px;vertical-align:middle;accent-color:#1f4e5f;cursor:pointer}
.dec-tbl2 .wc b{font-size:10px;color:#8d959f;font-weight:400;font-family:Consolas,monospace}
.dec-tbl2 .nm{color:#2b3138}
.dec-tbl2 .h2{font-size:10px;color:#8d959f}
.dec-tbl2 .cr{text-align:right;font-family:Consolas,Monaco,monospace;font-variant-numeric:tabular-nums}
.dec-tbl2 .civ{font-size:9.5px;color:#9aa2ab;font-family:Consolas,Monaco,monospace}
.dec-tbl2 tr.off td{opacity:.4}
.dec-out{margin-top:9px;padding-top:8px;border-top:1px solid #e6e9ec;font-size:12px}
.dec-out .row{display:flex;justify-content:space-between;padding:2px 0}
.dec-out .row b{font-family:Consolas,Monaco,monospace}
.dec-out .big{font-size:15px}
.dec-out .note{font-size:10.5px;color:#7a828c;margin-top:5px;line-height:1.7}
.note{font-size:11px;color:#7a828c;line-height:1.7;padding:6px 10px;border-left:2px solid #d7dade;
  background:#fafbfc;margin:0 8px 8px}
</style>
</head>
<body>
<header class="appbar">
  <div class="brand">
    <span class="brand-en">Spatial Explicit Batch Assessment</span>
    <span class="brand-cn">空间显式批量评估工作台</span>
  </div>
  <div class="proj" id="projName"></div>
  <div class="grow"></div>
  <div class="tag">离线网页版 * 生成于 __BUILT__</div>
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
        <i class="cdot l2"></i>区级中心地
        <i class="cdot l3"></i>社区级中心地
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
    <section class="card" id="decompCard" hidden>
      <h2>价格拆解 <span class="muted small" style="font-weight:400">拖动滑杆按你的需求重算</span></h2>
      <div class="pad" id="decompBody"></div>
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
      <h2>空间诊断 <span class="muted small" style="font-weight:400">全区口径，不是单个地块</span></h2>
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
function money(v){ return v==null?'-':NF.format(Math.round(v)); }
function brief(v){ return v==null?'-':(Math.abs(v)>=100?NF.format(Math.round(v)):v.toFixed(2)); }

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
function cname(c){
  if(c && c.name) return c.name;
  let b=-1,bd=1e18;
  for(let i=0;i<U.x.length;i++){
    const dx=U.x[i]-c.x, dy=U.y[i]-c.y, d=dx*dx+dy*dy;
    if(d<bd){bd=d;b=i;}
  }
  if(b<0) return '';
  let s=String(U.name[b]||'').replace(/居民委员会|居委会|村民委员会|村委会/g,'');
  return s.length>10?s.slice(0,10):s;
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

  // 水体在下面画，避免被地块色块盖住

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
  // 水体：画在地块之上，且不裁剪，河道才看得见
  if(BM.water && BM.water.length){
    ctx.fillStyle='#cfe0ee'; ctx.strokeStyle='#a8c4dc'; ctx.lineWidth=.6;
    ctx.beginPath();
    for(const f of BM.water){ if(!f||f.length<6)continue; ctx.moveTo(X(f[0]),Y(f[1]));
      for(let i=2;i<f.length;i+=2)ctx.lineTo(X(f[i]),Y(f[i+1])); ctx.closePath(); }
    ctx.fill(); ctx.stroke();
  }
  // 设施点：不同设施用不同形状，避免满屏都是圆点
  if(BM.points && BM.points.length){
    const sty={poi_metro:['#1f5f8b',3.0,1,'circle'],poi_shop:['#b26a1f',1.7,.62,'square'],
      poi_bus:['#5f6b78',1.2,.55,'circle'],poi_school:['#2c6e4f',2.0,.72,'triangle'],
      poi_cbd:['#9e3b30',3.8,1,'diamond']};
    for(const g of BM.points){
      const st=sty[g.id]||['#5f6b78',1.2,.55,'circle'];
      ctx.save(); ctx.globalAlpha=st[2]; ctx.fillStyle=st[0];
      for(const p of (g.xy||[])){
        const px=X(p[0]),py=Y(p[1]),r=st[1];
        ctx.beginPath();
        if(st[3]==='square') ctx.rect(px-r,py-r,r*2,r*2);
        else if(st[3]==='triangle'){ ctx.moveTo(px,py-r*1.2); ctx.lineTo(px+r*1.1,py+r*.8); ctx.lineTo(px-r*1.1,py+r*.8); ctx.closePath(); }
        else if(st[3]==='diamond'){ ctx.moveTo(px,py-r*1.15); ctx.lineTo(px+r*1.05,py); ctx.lineTo(px,py+r*1.15); ctx.lineTo(px-r*1.05,py); ctx.closePath(); }
        else ctx.arc(px,py,r,0,Math.PI*2);
        ctx.fill();
      }
      ctx.restore();
    }
  }
  // 中心地（不裁剪，区界附近的市级/区级中心也能显示）
  if(BM.centers){
    const col={1:'#7d2a1c',2:'#a86f16',3:'#2f5f7d'};
    for(const c of BM.centers){
      const r=c.level===1?6.5:(c.level===2?4.6:3.2);
      ctx.beginPath(); ctx.arc(X(c.x),Y(c.y),r,0,Math.PI*2);
      ctx.fillStyle=col[c.level]||'#666'; ctx.fill();
      ctx.strokeStyle='#fff'; ctx.lineWidth=1.3; ctx.stroke();
      const nm=cname(c);
      if(nm){
        ctx.font=(c.level===1?'600 10.5px':'10px')+' "Microsoft YaHei",sans-serif';
        ctx.fillStyle='rgba(32,36,40,.88)'; ctx.strokeStyle='rgba(255,255,255,.95)'; ctx.lineWidth=2.4;
        ctx.strokeText(nm,X(c.x)+r+3,Y(c.y)+3); ctx.fillText(nm,X(c.x)+r+3,Y(c.y)+3);
      }
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

  // 图例：三个数分别是最低、中位、最高，避免只给一串数字
  const g=ctx.createLinearGradient(0,0,120,0);
  const stops = F1.div?DIV:SEQ;
  stops.forEach((c,i)=>g.addColorStop(i/(stops.length-1),c));
  const rampEl=document.getElementById('ramp');
  rampEl.style.background=`linear-gradient(90deg,${stops.join(',')})`;
  const _u = F1.kind==='money'?' 元/㎡':'';
  document.getElementById('rampLabels').textContent =
    '最低 '+(F1.kind==='money'?money(lo):brief(lo))
    +'　中位 '+(F1.kind==='money'?money(at(.5)):brief(at(.5)))
    +'　最高 '+(F1.kind==='money'?money(hi):brief(hi)) + _u;
  const _np = (B.has_obs||[]).filter(Boolean).length;
  document.getElementById('mapStats').textContent =
    `有价格的地块 ${_np} 个　中位 ${F1.kind==='money'?money(at(.5)):brief(at(.5))}`;
}

/* ---------- 表格 ---------- */
function kv(el, rows){
  el.innerHTML = rows.map(([k,v])=>`<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}
function build(){
  document.getElementById('projName').textContent = String(P.name||'').split(' * ')[0];
  document.title = (String(P.name||'评估结果').split(' * ')[0]) + ' * 空间显式批量评估工作台系统';
  document.getElementById('mapTitle').textContent = F[S.field]?.name || '';

  const _n = B.network || {};
  kv(document.getElementById('projInfo'), [
    ['评估地块', NF.format(P.n_units)],
    ['有价格', NF.format(P.n_obs)],
    ['单元尺寸', (P.cell||0)+' 米（因子栅格）'],
    ['地理底图', '路网 2024 / 土地利用 2026 / OSM 设施'],
    ['价格来源', '14 区：6,132 个小区 2024 挂牌价；崇明/金山：区级均价合成'],
    ['路网节点', _n.n_nodes == null ? '-（内置包未保存）' : NF.format(_n.n_nodes)],
    ['吸附失败率', _n.snap_fail == null ? '-（内置包未保存）' : (_n.snap_fail*100).toFixed(2)+'%'],
    ['因子数量', (B.factors||[]).length],
  ]);

  const m = R.metrics||{}, tr=m.train||{}, cvr=m.cv_random||{}, cvs=m.cv_spatial||{};
  const rt = R.ratio||{}, mo = R.moran||{};
  const cod = rt.cod, prd = rt.prd;
  const codOk = cod != null && cod <= (rt.cod_max||15);
  const prdOk = prd != null && prd >= (rt.prd_low||0.98) && prd <= (rt.prd_high||1.03);
  kv(document.getElementById('metricTbl'), [
    ['训练解释度', `<span class="big ok">${((tr.r2||0)*100).toFixed(1)}%</span>`],
    ['空间留出解释度', `<span class="big">${((cvs.r2||0)*100).toFixed(1)}%</span>`],
    ['随机留出解释度', `${((cvr.r2||0)*100).toFixed(1)}%`],
    ['MAPE', ((tr.mape||0)).toFixed(1)+'%'],
    ['离散系数 COD', `${cod==null?'-':cod.toFixed(1)} <span class="pill ${codOk?'ok':'bad'}">${codOk?'达标':'超限'}</span>`],
    ['价格相关差 PRD', `${prd==null?'-':prd.toFixed(3)} <span class="pill ${prdOk?'ok':'bad'}">${prdOk?'达标':'超限'}</span>`],
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
    `道路 ${(BM.roads||[]).length} 段　水体 ${(BM.water||[]).length} 处　中心地 ${(BM.centers||[]).length} 个`;
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
const DECP = {};

function showDecomp(k){
  const d = (DATA.decomps || {})[String(k)];
  const card = document.getElementById('decompCard');
  const body = document.getElementById('decompBody');
  if (!d) { card.hidden = true; return; }
  card.hidden = false;
  DECP.cur = d;
  DECP.w = {};
  d.items.forEach(it => { DECP.w[it.code] = 0.5; });

  const issues = [];
  if (d.n < 100) issues.push('样本仅 ' + d.n + ' 套');
  if (d.r2 < 0.5) issues.push('局部 R² 仅 ' + d.r2.toFixed(2));
  if (d.bad_sign && d.bad_sign.length) issues.push('部分系数方向异常');
  if (Math.abs(d.unexplained) / (d.ask || 1) > 0.15) {
    issues.push(Math.round(Math.abs(d.unexplained) / d.ask * 100) + '% 价格未被解释');
  }
  const lvl = issues.length === 0 ? '高' : (issues.length === 1 ? '中' : '低');
  const cls = issues.length === 0 ? 'ok' : (issues.length === 1 ? 'mid' : 'bad');

  let html = '<div class="dec-sum">'
    + '<div><span class="k">局部基准价</span><span class="v">' + NF.format(d.base) + '</span></div>'
    + '<div><span class="k">因素加总</span><span class="v">' + NF.format(d.model) + '</span></div>'
    + '<div><span class="k">未解释</span><span class="v">' + (d.unexplained>=0?'+':'') + NF.format(d.unexplained) + '</span></div>'
    + '<div><span class="k">样本</span><span class="v">' + d.n + ' 套 / ' + Math.round(d.radius) + 'm</span></div>'
    + '</div>';
  html += '<div class="dec-q"><span class="pill ' + cls + '">拆解可信度 ' + lvl + '</span>'
    + (issues.length ? '　' + issues.join('；') : '') + '</div>';

  html += '<table class="dec-tbl2">';
  for (const it of d.items) {
    const w = 50;
    html += '<tr data-code="' + it.code + '">'
      + '<td class="wc"><input type="range" min="0" max="100" step="10" value="' + w + '" data-c="' + it.code + '"><b>' + w + '%</b></td>'
      + '<td class="nm">' + it.name + (it.hint ? '<div class="h2">' + it.hint + '</div>' : '') + '</td>'
      + '<td class="cr">' + (it.c >= 0 ? '+' : '') + NF.format(it.c)
      + '<div class="civ">' + NF.format(it.lo) + '~' + NF.format(it.hi) + (it.sig ? '' : '?') + '</div></td>'
      + '</tr>';
  }
  html += '</table>';
  html += '<div class="dec-out" id="decOut"></div>';
  body.innerHTML = html;

  body.querySelectorAll('input[data-c]').forEach(sl => {
    sl.oninput = () => {
      const v = parseInt(sl.value, 10) / 100;
      DECP.w[sl.dataset.c] = v;
      sl.parentNode.querySelector('b').textContent = Math.round(v * 100) + '%';
      sl.closest('tr').classList.toggle('off', v === 0);
      renderDecOut();
    };
  });
  renderDecOut();
}

function renderDecOut(){
  const d = DECP.cur;
  if (!d) return;
  let adapted = d.base;
  const list = [];
  let anyOff = false;
  for (const it of d.items) {
    const pref = DECP.w[it.code] == null ? 0.5 : DECP.w[it.code];
    const w = pref * 2;
    adapted += w * it.c;
    if (Math.abs(w - 1) > 1e-9) {
      anyOff = true;
      if (w < 1 && it.c > 0) list.push({ name: it.name, cut: (1 - w) * it.c });
    }
  }
  if (!anyOff) adapted = d.model;
  const diff = d.model - adapted;
  const area = 90;
  let h = '<div class="row"><span>市场平均价</span><b>' + NF.format(d.model) + ' 元/㎡</b></div>';
  h += '<div class="row"><span>按你的支付意愿</span><b class="big">' + NF.format(Math.round(adapted)) + ' 元/㎡</b></div>';
  if (anyOff) {
    h += '<div class="row"><span>' + (diff > 0 ? '你为不需要的部分少付' : '你的支付意愿高于市场') + '</span>'
      + '<b style="color:' + (diff > 0 ? '#8a3b2c' : '#2f6b46') + '">' + NF.format(Math.round(Math.abs(diff))) + ' 元/㎡</b></div>';
    h += '<div class="note">按 ' + area + ' ㎡ 折算：市场 ' + NF.format(Math.round(d.model * area))
      + ' 元 -> 适配 ' + NF.format(Math.round(adapted * area)) + ' 元（差 '
      + NF.format(Math.round(Math.abs(diff) * area)) + ' 元）</div>';
  } else {
    h += '<div class="note">各项均为 50%（市场平均）时，适配价与市场平均价相同。调整滑杆即可看到差异。</div>';
  }
  document.getElementById('decOut').innerHTML = h;
}

function showDetail(k){
  const _ut = (DATA.boot.units && DATA.boot.units.use_type || [])[k];
  const _ud = (DATA.boot.units && DATA.boot.units.use_detail || [])[k] || _ut;
  if (_ut && _ut !== '住宅') {
    const nm = (DATA.boot.units.name || [])[k] || (DATA.boot.units.id || [])[k];
    const body = document.getElementById('detailBody') || document.querySelector('#detailCard .pad');
    const b = body || document.body;
    b.innerHTML = '<div class="pad">'
      + '<div style="display:flex;justify-content:space-between;padding:3px 0">'
      + '<span style="color:#7a828c">单元用途</span><b>' + _ud + '</b></div>'
      + '<div style="font-size:11px;color:#8d959f;line-height:1.8;margin-top:6px">'
      + '该单元为' + _ud + '用地，不参与估值与精度统计。</div>'
      + '<div style="font-size:11px;color:#7a828c;margin-top:6px">' + nm + '</div>'
      + '</div>';
    return;
  }
  const card=document.getElementById('detailCard'), body=document.getElementById('detailBody');
  card.hidden=false;
  const base=(R.arrays||{});
  const rows=[];
  rows.push(['所属街道', U.admin?U.admin[k]:'-']);
  rows.push(['面积', NF.format(Math.round(U.area?U.area[k]:0))+' ㎡']);
  rows.push(['坐标', `${Math.round(U.x[k])}, ${Math.round(U.y[k])}`]);
  rows.push(['有价格', B.has_obs&&B.has_obs[k]?'是':'否']);
  rows.push(['估值中位', base.est_median?money(base.est_median[k]):'-']);
  rows.push(['区间', base.p_low?`${money(base.p_low[k])} ~ ${money(base.p_high[k])}`:'-']);
  if(base.resid) rows.push(['残差', Number(base.resid[k]).toFixed(4)]);

  let html = '<table class="kv">'+rows.map(([a,b])=>`<tr><td>${a}</td><td>${b}</td></tr>`).join('')+'</table>';
  html += '<div style="margin-top:8px;font-size:11px;color:#7a828c">全部因子取值</div>';
  html += '<table class="tbl">'+Object.entries(F).filter(([c])=>!['est_median','est_mean','p_low','p_high','resid'].includes(c))
    .map(([c,v])=>`<tr><td>${v.name}</td><td class="num">${Number(v.values[k]).toFixed(3)}</td></tr>`).join('')+'</table>';
  body.innerHTML = html;
  showDecomp(k);
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

/* 支持 #unit=<序号> 直接打开某单元（含价格拆解） */
(function () {
  const m = (location.hash || '').match(/^#unit=(\d+)/);
  if (!m) return;
  const k = parseInt(m[1], 10);
  if (!(k >= 0 && k < U.x.length)) return;
  setTimeout(() => { S.sel = k; draw(); showDetail(k); }, 300);
})();
</script>
</body>
</html>
"""

def _short_name(v):
    """项目名去掉 * 真实地理 + 价格锚定这类后缀，页面上只显示区名。"""
    return str(v or "").split(" * ")[0]

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=os.path.join(HERE, "data", "districts/徐汇区.bundle"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not os.path.exists(args.bundle):
        print("找不到数据包：%s" % args.bundle)
        return 2

    print("正在读取数据包并构造结果 ...")
    payload = build_payload(args.bundle)

    title = (payload["boot"].get("project") or {}).get("name") or "评估结果"
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = (HTML_TEMPLATE
            .replace("__TITLE__", title + " * 离线网页版")
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
