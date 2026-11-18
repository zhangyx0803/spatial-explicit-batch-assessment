# -*- coding: utf-8 -*-
"""把上海 16 个区全部跑一遍，输出分区对比表。

用法：
    python make_district_table.py                # 全部 16 区
    python make_district_table.py --districts 徐汇区 静安区
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = os.path.dirname(os.path.abspath(__file__))


def run_one(district: str, cell: float, radius: float):
    import numpy as np

    from seba.config import ProjectConfig
    from seba.diagnosis import district_summary, morans_i
    from seba.engine import FactorEngine
    from seba.realdata import build_district_dataset
    from seba.ratios import ratio_study
    from seba.stats import fit_and_evaluate

    t0 = time.perf_counter()
    ds, rep = build_district_dataset(district, cell_m=cell, radius_m=radius)

    with open(os.path.join(HERE, "config", "factors_real.yaml"), "r", encoding="utf-8") as fh:
        cfg = ProjectConfig.from_yaml(fh.read())
    FactorEngine(cfg, ds).run()

    feats = []
    for c in cfg.model["features"]:
        v = ds.attrs.get(c)
        if v is None:
            continue
        lo, hi = np.percentile(v, 2), np.percentile(v, 98)
        if np.isfinite(lo) and np.isfinite(hi) and abs(hi - lo) > 1e-12:
            feats.append(c)

    import numpy as _np

    obs = ds.obs
    X_all = ds.design_matrix(feats)
    X = X_all[obs.unit_idx]
    y = obs.unit_price
    bx = ds.units.x[obs.unit_idx]
    span = (bx.max() - bx.min()) or 1.0
    k = int((cfg.model.get("cv") or {}).get("spatial_folds", 5))
    block = _np.minimum(((bx - bx.min()) / span * k).astype(int), k - 1)
    bundle = fit_and_evaluate(X, y, feats, block, cfg.model)
    ratio = ratio_study(_np.exp(bundle.oof_log), y, cod_max=15.0)
    ui = obs.unit_idx
    mo = morans_i(bundle.resid_log, ds.units.x[ui], ds.units.y[ui], k=6, n_perm=299, seed=7)
    streets = district_summary(ds.units.admin_code[ui], bundle.resid_log, threshold=1.5)

    # 最强三个因子（按 |t|）
    m_ols = bundle.ols
    coefs = sorted(zip(list(m_ols.names)[1:], list(m_ols.coef)[1:], list(m_ols.t)[1:]),
                   key=lambda t: -abs(float(t[2])))[:3]

    return {
        "区县": district,
        "单元数": ds.n_units,
        "成交数": ds.n_obs(),
        "路网段": rep.n_road_segments if hasattr(rep, "n_road_segments") else 0,
        "因子数": len(feats),
        "训练R2": round(float(bundle.train_metrics["r2"]), 4),
        "随机CV_R2": round(float(bundle.cv_random["r2"]), 4),
        "空间CV_R2": round(float(bundle.cv_spatial["r2"]), 4),
        "COD": round(float(ratio["cod"]), 1),
        "PRD": round(float(ratio["prd"]), 3),
        "中位比率": round(float(ratio["median_ratio"]), 3),
        "估值中位": int(_np.median(_np.exp(bundle.fitted_log))),
        "Moran_I": round(float(mo.i), 3),
        "失配街道": len([x for x in streets if x[3] != "无明显偏离"]),
        "街道总数": len(streets),
        "最强因子": coefs[0][0] if coefs else "",
        "最强因子t": round(float(coefs[0][2]), 2) if coefs else 0,
        "耗时s": round(time.perf_counter() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--districts", nargs="*", default=None)
    ap.add_argument("--cell", type=float, default=120.0)
    ap.add_argument("--radius", type=float, default=500.0)
    ap.add_argument("--out", default=os.path.join(HERE, "dist_table"))
    args = ap.parse_args()

    from seba.realdata import list_districts

    if args.districts:
        targets = args.districts
    else:
        targets = [d for d, _ in list_districts()]

    print("=" * 78)
    print("  上海分区批量评估  ——  %d 个区" % len(targets))
    print("=" * 78)

    rows = []
    for i, d in enumerate(targets, 1):
        print("\n[%d/%d] %s ……" % (i, len(targets), d), flush=True)
        try:
            r = run_one(d, args.cell, args.radius)
            rows.append(r)
            print("      单元 %-5d  R2 %.3f  空间CV %.3f  COD %5.1f  PRD %.3f  最强 %s (t=%.1f)  %.0fs"
                  % (r["单元数"], r["训练R2"], r["空间CV_R2"], r["COD"], r["PRD"],
                     r["最强因子"], r["最强因子t"], r["耗时s"]), flush=True)
        except Exception as exc:
            print("      [失败] %s: %s" % (type(exc).__name__, exc))
            traceback.print_exc(limit=2)

    if not rows:
        print("\n没有成功的结果。")
        return 1

    # ---- 输出 ----
    os.makedirs(args.out, exist_ok=True)
    cols = list(rows[0].keys())

    import csv

    csv_path = os.path.join(args.out, "上海分区对比表.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print("\n已输出：%s" % csv_path)

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "分区对比"
        ws.append(cols)
        for r in rows:
            ws.append([r[c] for c in cols])
        head_fill = PatternFill("solid", fgColor="1F4E5F")
        for c in range(1, len(cols) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center")
        widths = {"区县": 12, "最强因子": 24}
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = widths.get(c, 11)
        ws.freeze_panes = "B2"

        xlsx_path = os.path.join(args.out, "上海分区对比表.xlsx")
        wb.save(xlsx_path)
        print("已输出：%s" % xlsx_path)
    except Exception as exc:
        print("Excel 输出失败：%s" % exc)

    # ---- 控制台汇总 ----
    print("\n" + "=" * 78)
    hdr = "%-8s %6s %7s %7s %7s %6s %6s %6s" % (
        "区县", "单元", "训练R2", "空间CV", "COD", "PRD", "Moran", "失配")
    print(hdr)
    print("-" * 78)
    for r in sorted(rows, key=lambda x: -x["空间CV_R2"]):
        print("%-8s %6d %7.3f %7.3f %7.1f %6.3f %6.3f %3d/%d"
              % (r["区县"], r["单元数"], r["训练R2"], r["空间CV_R2"],
                 r["COD"], r["PRD"], r["Moran_I"], r["失配街道"], r["街道总数"]))
    ok = [r for r in rows if r["COD"] <= 15 and 0.98 <= r["PRD"] <= 1.03]
    print("-" * 78)
    print("COD 与 PRD 双达标：%d / %d 个区" % (len(ok), len(rows)))
    if ok:
        print("  " + "、".join(r["区县"] for r in ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
