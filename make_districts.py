# -*- coding: utf-8 -*-
"""为上海 16 个区各生成一个精简数据包，供网页版切换。

产物：
    data/districts/<区名>.bundle     每个约 0.8-2 MB
    data/districts/_index.json       区名、单元数、成交数、R²
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
OUT = os.path.join(HERE, "data", "districts")

def main() -> int:
    import numpy as np

    from seba.bundle import save_bundle
    from seba.config import ProjectConfig
    from seba.engine import FactorEngine
    from seba.realdata import build_district_dataset, list_districts
    from seba.stats import fit_and_evaluate

    os.makedirs(OUT, exist_ok=True)
    cfg_path = os.path.join(HERE, "config", "factors_real.yaml")

    targets = [d for d, _ in list_districts()]
    sel = [a for a in sys.argv[1:] if not a.startswith("-")]
    if sel:
        targets = [d for d in targets if d in sel]
    index_path = os.path.join(OUT, "_index.json")
    index = []
    if sel and os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as fh:
                index = json.load(fh)
        except Exception:
            index = []
    t_all = time.time()

    for i, d in enumerate(targets, 1):
        t0 = time.time()
        try:
            ds, rep = build_district_dataset(d, cell_m=120, radius_m=500)
            cfg = ProjectConfig.from_yaml(open(cfg_path, encoding="utf-8").read())
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

            path = os.path.join(OUT, "%s.bundle" % d)
            save_bundle(ds, path, rep.notes, {"district": d}, slim=True)
            mb = os.path.getsize(path) / 1048576
            row = {
                "name": d, "units": ds.n_units, "obs": ds.n_obs(),
                "r2": round(float(b.train_metrics["r2"]), 3),
                "cv": round(float(b.cv_spatial["r2"]), 3),
                "mb": round(mb, 2),
            }
            index = [x for x in index if x.get("name") != d] + [row]
            print("[%2d/%d] %-6s %4d 单元 %4d 成交  R²=%.3f  %.1f MB  %.0fs"
                  % (i, len(targets), d, ds.n_units, ds.n_obs(),
                     b.train_metrics["r2"], mb, time.time() - t0), flush=True)
        except Exception as exc:
            print("[%2d/%d] %-6s 失败：%s" % (i, len(targets), d, exc), flush=True)

    with open(os.path.join(OUT, "_index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)

    print("\n完成 %d 个区，总用时 %.1f 分钟" % (len(index), (time.time() - t_all) / 60))
    return 0

if __name__ == "__main__":
    sys.exit(main())
