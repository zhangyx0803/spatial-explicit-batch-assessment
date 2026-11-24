# -*- coding: utf-8 -*-
"""交付前体检：不依赖 F 盘的部分。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = os.path.dirname(os.path.abspath(__file__))

def line(t):
    print("\n" + "=" * 78)
    print(" " + t)
    print("=" * 78)

def main() -> int:
    import numpy as np

    # ---------- 1. 演示场景（内置，不依赖 F 盘） ----------
    line("1. 内置演示场景能否跑通（不依赖原始数据）")
    from seba.config import ProjectConfig
    from seba.engine import FactorEngine
    from seba.grid import build_test_dataset
    from seba.stats import fit_and_evaluate

    cfg = ProjectConfig.from_yaml(
        open(os.path.join(HERE, "config", "factors.yaml"), encoding="utf-8").read())
    sc = build_test_dataset(seed=20261117, nx=30, ny=30, cell=250)
    eng = FactorEngine(cfg, sc.dataset)
    rep = eng.run()
    print("  因子计算：%d 个，用时 %.1fs" % (len(sc.dataset.attrs), getattr(rep, "total_seconds", getattr(rep, "elapsed", 0.0))))
    feats = [c for c in cfg.model["features"] if c in sc.dataset.attrs]
    ui = sc.dataset.obs.unit_idx
    X = sc.dataset.design_matrix(feats)[ui]
    y = sc.dataset.obs.unit_price
    bx = sc.dataset.units.x[ui]
    k = 5
    block = np.minimum(((bx - bx.min()) / ((bx.max() - bx.min()) or 1) * k).astype(int), k - 1)
    b = fit_and_evaluate(X, y, feats, block, cfg.model)
    print("  模型：R²=%.3f  空间CV=%.3f  样本=%d" %
          (b.train_metrics["r2"], b.cv_spatial["r2"], len(y)))

    # ---------- 2. 16 个区数据包的因子完整性 ----------
    line("2. 内置 16 区数据包：因子可用性")
    from seba.bundle import load_bundle

    ddir = os.path.join(HERE, "data", "districts")
    names = sorted(f[:-7] for f in os.listdir(ddir) if f.endswith(".bundle"))
    want = ["rt_metro_time", "rt_shop_1km", "rt_green_500", "rt_comm_share",
            "rt_built_share", "cp_gravity", "rt_isect_dens", "rt_road_density",
            "sch_dist", "sch_class_cnt", "sch_group"]
    print("  %-8s %6s %6s %5s  %s" % ("区", "单元", "成交", "因子", "缺失/恒定因子"))
    problems = []
    for d in names:
        ds, notes, extra = load_bundle(os.path.join(ddir, d + ".bundle"))
        miss, const = [], []
        for c in want:
            v = ds.attrs.get(c)
            if v is None:
                miss.append(c)
                continue
            lo, hi = np.percentile(v, 2), np.percentile(v, 98)
            if abs(float(hi) - float(lo)) < 1e-12:
                const.append(c)
        tag = []
        if miss:
            tag.append("缺 " + ",".join(miss))
        if const:
            tag.append("恒定 " + ",".join(const))
        print("  %-8s %6d %6d %5d  %s" % (d, ds.n_units, ds.n_obs(), len(ds.attrs),
                                          "；".join(tag) if tag else "-"))
        if miss or const:
            problems.append((d, miss, const))

    # ---------- 3. 学区因子覆盖 ----------
    line("3. 学区因子覆盖（sch_* 是否有有效取值）")
    print("  %-8s %10s %10s %10s" % ("区", "sch_dist", "sch_class_cnt", "sch_group"))
    for d in names:
        ds, _, _ = load_bundle(os.path.join(ddir, d + ".bundle"))
        row = []
        for c in ("sch_dist", "sch_class_cnt", "sch_group"):
            v = ds.attrs.get(c)
            if v is None:
                row.append("缺失")
            else:
                lo, hi = np.percentile(v, 2), np.percentile(v, 98)
                row.append("恒定" if abs(float(hi) - float(lo)) < 1e-12 else "有效")
        print("  %-8s %10s %10s %10s" % (d, row[0], row[1], row[2]))

    # ---------- 4. 拆解可用性 ----------
    line("4. 价格拆解可用性（每个区随机取 3 个有成交单元）")
    from seba.decompose import decompose

    cfgr = ProjectConfig.from_yaml(
        open(os.path.join(HERE, "config", "factors_real.yaml"), encoding="utf-8").read())
    rng = np.random.default_rng(7)
    fail = 0
    for d in names[:6]:
        ds, _, _ = load_bundle(os.path.join(ddir, d + ".bundle"))
        feats = [c for c in cfgr.model["features"] if c in ds.attrs]
        w = {c: 1.0 for c in feats}
        ok, err = 0, ""
        for i in rng.choice(np.asarray(ds.obs.unit_idx), 3, replace=False):
            try:
                decompose(ds, w, int(i), radius=1500.0, min_n=120, n_boot=8)
                ok += 1
            except Exception as exc:
                err = str(exc)[:50]
        print("  %-8s 成功 %d/3  %s" % (d, ok, err))
        fail += (3 - ok)

    line("结论")
    print("  演示场景：可跑通")
    print("  16 区数据包：%d 区存在缺失或恒定因子" % len(problems))
    print("  拆解失败总数：%d" % fail)
    return 0

if __name__ == "__main__":
    sys.exit(main())
