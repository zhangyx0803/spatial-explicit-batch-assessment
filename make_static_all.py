# -*- coding: utf-8 -*-
"""为上海 16 个区各生成一个离线 HTML，并生成一个入口页。

产物：
    dist_static/index.html            入口（选区面板）
    dist_static/<区>_网页版.html       每个区一个单文件
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dist_static")

INDEX = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>空间显式批量评估工作台系统 · 离线成果</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#eef0f3;font:13px/1.6 "Microsoft YaHei","PingFang SC",sans-serif;color:#232a31}
.wrap{max-width:960px;margin:0 auto;padding:48px 28px}
h1{margin:0 0 6px;font-size:22px;color:#1f3850;letter-spacing:.5px}
.sub{margin:0 0 26px;color:#6d757e;font-size:12.5px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
a.card{display:block;background:#fff;border:1px solid #e2e6ea;border-radius:4px;
  padding:14px 15px;text-decoration:none;color:inherit;transition:border-color .12s,background .12s}
a.card:hover{border-color:#1f4e5f;background:#f6fafb}
a.card b{display:block;font-size:14px;margin-bottom:6px;font-weight:600}
a.card span{display:block;font-size:10.5px;color:#8d959f;font-family:Consolas,monospace}
.foot{margin-top:26px;padding-top:14px;border-top:1px solid #dfe3e7;
  font-size:11px;color:#8d959f;line-height:1.9}
@media(max-width:820px){.grid{grid-template-columns:repeat(2,1fr)}}
</style></head><body><div class="wrap">
<h1>空间显式批量评估工作台系统</h1>
<p class="sub">离线成果浏览 · 内置上海 16 个区 · 点击任意一个区打开</p>
<div class="grid">__CARDS__</div>
<div class="foot">
每个区是一个独立 HTML 文件，双击即可用浏览器打开，不需要服务器与网络。<br>
页面内可看估值地图、精度指标、模型系数、空间诊断、单元详情与价格拆解（含偏好调节）。<br>
本批数据中 14 个区使用小区级真实挂牌价，崇明、金山两区因小区稀疏仍用合成价；价格来源见各区页面。
</div></div></body></html>
"""

CARD = ('<a class="card" href="{file}"><b>{name}</b>'
        '<span>{units} 个地块　{obs} 个有价格</span>'
        '<span>模型解释度 {r2}%</span></a>')


def main() -> int:
    from make_static_html import HTML_TEMPLATE, build_payload

    ddir = os.path.join(HERE, "data", "districts")
    names = sorted(f[:-7] for f in os.listdir(ddir) if f.endswith(".bundle"))
    if not names:
        print("没有找到 data/districts/*.bundle")
        return 2
    os.makedirs(OUT, exist_ok=True)

    cards = []
    t_all = time.time()
    for i, name in enumerate(names, 1):
        bundle = os.path.join(ddir, name + ".bundle")
        t0 = time.time()
        try:
            payload = build_payload(bundle)
        except Exception as exc:
            print("[%2d/%d] %-6s 失败：%s" % (i, len(names), name, exc), flush=True)
            continue
        boot = payload["boot"]
        proj = boot.get("project") or {}
        r2 = ((boot.get("result") or {}).get("metrics") or {}).get("train", {}).get("r2")
        title = proj.get("name") or (name + " 评估结果")
        blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        html = (HTML_TEMPLATE
                .replace("__TITLE__", title + "（离线网页版）")
                .replace("__BUILT__", payload["built"])
                .replace("__PAYLOAD__", blob))
        fn = "%s_网页版.html" % name
        with open(os.path.join(OUT, fn), "w", encoding="utf-8") as fh:
            fh.write(html)
        mb = os.path.getsize(os.path.join(OUT, fn)) / 1048576
        cards.append(CARD.format(
            file=fn, name=name,
            units="{:,.0f}".format(proj.get("n_units") or 0),
            obs="{:,.0f}".format(proj.get("n_obs") or 0),
            r2=("%.1f" % (r2 * 100)) if r2 is not None else "—",
        ))
        print("[%2d/%d] %-6s %5.2f MB  %.0fs" % (i, len(names), name, mb, time.time() - t0), flush=True)

    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(INDEX.replace("__CARDS__", "\n".join(cards)))

    tot = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)) / 1048576
    print("\n入口页：%s" % os.path.join(OUT, "index.html"))
    print("共 %d 个区，合计 %.1f MB，用时 %.1f 分钟" % (len(cards), tot, (time.time() - t_all) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
