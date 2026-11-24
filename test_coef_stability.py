# -*- coding: utf-8 -*-
"""检验系数在空间上的稳定性：16 个区各拟合一次，比较同一因子的系数差异。

这个实验回答一个问题：
    上海全市拟合出来的系数，能不能代表某个具体片区？
如果各区间系数离散度很大，说明"用一个系数预测全市"不成立，
但"在局部拟合、做价格拆分"仍然可行。
"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = os.path.dirname(os.path.abspath(__file__))

def one(district: str):
    import numpy as np

    from seba.config import ProjectConfig
    from seba.engine import FactorEngine
    from seba.realdata import build_district_dataset
    from seba.stats import fit_and_evaluate

    ds, rep = build_district_dataset(district, cell_m=120, radius_m=500)
    cfg = ProjectConfig.from_yaml(open(os.path.join(HERE, "config", "factors_real.yaml"),
                                       encoding="utf-8").read())
    FactorEngine(cfg, ds).run()
    feats = []
    for c in cfg.model["features"]:
        v = ds.attrs.get(c)
        if v is None:
            continue
        lo, hi = np.percentile(v, 2), np.percentile(v, 98)
        if np.isfinite(lo) and np.isfinite(hi) and abs(hi - lo) > 1e-12:
            feats.append(c)
    obs = ds.obs
    ui = obs.unit_idx
    X = ds.design_matrix(feats)[ui]
    y = obs.unit_price
    bx = ds.units.x[ui]
    k = 5
    block = np.minimum(((bx - bx.min()) / ((bx.max() - bx.min()) or 1) * k).astype(int), k - 1)
    b = fit_and_evaluate(X, y, feats, block, cfg.model)
    out = {}
    for n, c in zip(b.ols.names[1:], b.ols.coef[1:]):
        out[n] = float(c)
    out["_n"] = int(len(y))
    out["_r2"] = float(b.train_metrics["r2"])
    return out

def main() -> int:
    from seba.realdata import list_districts

    targets = [d for d, _ in list_districts()]
    rows = {}
    for i, d in enumerate(targets, 1):
        try:
            rows[d] = one(d)
            print("[%2d/%d] %-6s OK" % (i, len(targets), d), flush=True)
        except Exception as exc:
            print("[%2d/%d] %-6s 失败 %s" % (i, len(targets), d, exc))
            traceback.print_exc(limit=1)

    import numpy as np

    codes = [c for c in next(iter(rows.values())).keys() if not c.startswith("_")]
    districts = list(rows.keys())

    print("\n" + "=" * 96)
    print("  同一因子在 16 个区的系数   （括号内为 标准差/均值 的绝对值，即变异系数）")
    print("=" * 96)
    print("%-26s %10s %10s %10s %10s %8s" % ("因子", "最小", "中位", "最大", "极差/中位", "符号一致"))
    print("-" * 96)
    for c in codes:
        vals = np.array([rows[d][c] for d in districts if c in rows[d]], dtype=float)
        med = float(np.median(vals))
        rng = float(vals.max() - vals.min())
        same_sign = bool((vals > 0).all() or (vals < 0).all())
        rel = rng / abs(med) if abs(med) > 1e-12 else float("inf")
        print("%-26s %10.5f %10.5f %10.5f %10.1f %8s"
              % (c, vals.min(), med, vals.max(), rel, "是" if same_sign else "否"))

    # 样本内 vs 跨区外推的对比
    print("\n" + "=" * 96)
    print("  结论")
    print("=" * 96)
    unstable = []
    for c in codes:
        vals = np.array([rows[d][c] for d in districts if c in rows[d]], dtype=float)
        med = abs(float(np.median(vals)))
        rng = float(vals.max() - vals.min())
        if med > 1e-12 and rng / med > 1.0:
            unstable.append((c, rng / med))
    if unstable:
        print("  系数极差超过中位数 1 倍（说明跨区不可通用）的因子：")
        for c, r in sorted(unstable, key=lambda t: -t[1]):
            print("    %-26s 极差是中位的 %.1f 倍" % (c, r))
    else:
        print("  所有因子跨区极差都在中位数的 1 倍以内")
    return 0

if __name__ == "__main__":
    sys.exit(main())
