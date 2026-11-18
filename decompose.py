# -*- coding: utf-8 -*-
"""价格拆解 + 个性化适配（命令行入口）。

核心逻辑在 seba/decompose.py，这个文件只负责解析参数、打印报表。

用法：
    python decompose.py --unit V00247
    python decompose.py --unit V00247 --price 118640 --radius 1200
    python decompose.py --unit V00247 --pref rt_metro_time=0 sch_dist=0
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
_v = os.path.join(_HERE, "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = _HERE


def main() -> int:
    ap = argparse.ArgumentParser(description="价格拆解 + 个性化适配")
    ap.add_argument("--bundle", default=os.path.join(HERE, "data", "demo_xuhui.bundle"))
    ap.add_argument("--unit", required=True, help="目标单元编号，如 V00247")
    ap.add_argument("--price", type=float, default=None,
                    help="待拆解的价格（元/㎡）；不给就用该单元的成交价")
    ap.add_argument("--radius", type=float, default=1500.0, help="局部样本半径（米）")
    ap.add_argument("--min-n", type=int, default=60, help="最少样本数，不足则扩半径")
    ap.add_argument("--area", type=float, default=90.0, help="折算总价用的面积")
    ap.add_argument("--pref", nargs="*", default=[],
                    help="支付意愿权重，如 rt_metro_time=0 sch_dist=0")
    args = ap.parse_args()

    from seba.bundle import load_bundle
    from seba.config import ProjectConfig
    from seba.decompose import decompose, personalize, render

    ds, notes, extra = load_bundle(args.bundle)
    cfg = ProjectConfig.from_yaml(open(os.path.join(HERE, "config", "factors_real.yaml"),
                                       encoding="utf-8").read())
    feats = [c for c in cfg.model["features"] if c in ds.attrs]
    weights = {c: 1.0 for c in feats}
    for kv in args.pref:
        if "=" in kv:
            k, v = kv.split("=", 1)
            if k in weights:
                weights[k] = float(v)

    ids = list(ds.units.unit_id)
    if args.unit not in ids:
        print("找不到单元 %s（示例：%s）" % (args.unit, ", ".join(ids[:5])))
        return 2
    idx = ids.index(args.unit)

    dec = decompose(ds, weights, idx, asking_price=args.price,
                    radius=args.radius, min_n=args.min_n)
    adapted, wasted = personalize(dec, weights)
    print(render(dec, weights, adapted, wasted, area=args.area))
    return 0


if __name__ == "__main__":
    sys.exit(main())
