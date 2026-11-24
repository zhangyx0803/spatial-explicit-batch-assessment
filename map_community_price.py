# -*- coding: utf-8 -*-
"""把已地理编码的小区匹配到评估单元，输出单元级真实均价。

用法：
    python map_community_price.py [--radius 800]

产物：
    data/external/unit_price_real.csv   单元ID, 区县, 居委, 匹配小区数, 中位挂牌价
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))

EXT = os.path.join(HERE, "data", "external")
XY = os.path.join(EXT, "community_xy.csv")
OUT = os.path.join(EXT, "unit_price_real.csv")
DDIR = os.path.join(HERE, "data", "districts")

# 与 realdata 一致的局部平面投影（用上海中心作基准即可，误差厘米级）
LAT0, LON0 = 31.2304, 121.4737
KX = 111320.0 * math.cos(math.radians(LAT0))
KY = 110540.0

def proj(lon, lat):
    return (lon - LON0) * KX, (lat - LAT0) * KY

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--radius", type=float, default=800.0)
    ap.add_argument("--min-n", type=int, default=1)
    args = ap.parse_args()

    from seba.bundle import load_bundle

    if not os.path.exists(XY):
        print("找不到", XY, "请先运行 geocode_all.py")
        return 2

    coms = []
    for r in csv.DictReader(open(XY, encoding="utf-8-sig")):
        try:
            lon, lat = float(r["经度"]), float(r["纬度"])
            p = float(r["挂牌单价"])
        except ValueError:
            continue
        if not (120.8 < lon < 122.2 and 30.6 < lat < 31.9):
            continue
        x, y = proj(lon, lat)
        coms.append((r["区县"], r["小区名"], p, x, y))
    print("有效小区 %d 个" % len(coms), flush=True)

    # 按区县分桶，减少匹配计算量
    buckets = defaultdict(list)
    for d, nm, p, x, y in coms:
        buckets[d].append((nm, p, x, y))

    rows = []
    total_u = total_hit = 0
    for fn in sorted(os.listdir(DDIR)):
        if not fn.endswith(".bundle") or fn.startswith("_"):
            continue
        d = fn[:-7]
        ds, _, _ = load_bundle(os.path.join(DDIR, fn))
        pool = buckets.get(d, [])
        # 本区没有小区时，用全市小区兜底（边界小区常被归到邻区）
        pool_all = [(nm, p, x, y) for _d, nm, p, x, y in coms] if len(pool) < 20 else None
        n_unit = ds.n_units
        hit = 0
        for i in range(n_unit):
            ux, uy = float(ds.units.x[i]), float(ds.units.y[i])
            best = []
            src = pool if pool else [(nm2, p2, x2, y2) for _d2, nm2, p2, x2, y2 in coms]
            for nm, p, x, y in src:
                if abs(x - ux) > args.radius or abs(y - uy) > args.radius:
                    continue
                if math.hypot(x - ux, y - uy) <= args.radius:
                    best.append(p)
            if not best and pool_all:
                for nm, p, x, y in pool_all:
                    if math.hypot(x - ux, y - uy) <= args.radius:
                        best.append(p)
            if len(best) >= args.min_n:
                rows.append([str(ds.units.unit_id[i]), d,
                             str(ds.units.name[i]) if getattr(ds.units, "name", None) is not None else "",
                             len(best), int(np.median(best))])
                hit += 1
        print("  %-6s %4d 单元  命中 %4d (%.0f%%)" % (d, n_unit, hit, 100 * hit / max(1, n_unit)), flush=True)
        total_u += n_unit
        total_hit += hit

    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单元ID", "区县", "居委", "匹配小区数", "中位挂牌价"])
        w.writerows(rows)
    print("\n合计 %d/%d = %.0f%% 单元有真实小区价 -> %s"
          % (total_hit, total_u, 100 * total_hit / max(1, total_u), OUT))
    return 0

if __name__ == "__main__":
    sys.exit(main())
