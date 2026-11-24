# -*- coding: utf-8 -*-
"""真实数据版运行入口：上海某区的真实路网 / 土地利用 / 村界。

    python run_real.py                       # 默认长宁区
    python run_real.py --district 徐汇区
    python run_real.py --district 浦东新区 --cell 150
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import numpy as np

_BASE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_BASE, 'vendor')
if os.path.isdir(_VENDOR):
    sys.path.insert(0, _VENDOR)   # 项目内可选的 scipy/pyogrio；放最前保证 numpy 版本配套
sys.path.insert(0, _BASE)

from seba.diagnosis import district_summary, morans_i, residual_map_png
from seba.engine import FactorEngine
from seba.config import ProjectConfig
from seba.ratios import ratio_study
from seba.realdata import DISTRICT_PRICE, build_district_dataset, list_districts
from seba.report import write_calibration_report, write_workbook
from seba.stats import fit_and_evaluate

def hr(t=""):
    print("\n" + "=" * 74)
    if t:
        print(t)
        print("=" * 74)

def main(argv=None):
    ap = argparse.ArgumentParser(description="真实数据批量评估")
    ap.add_argument("--config", default=os.path.join("config", "factors_real.yaml"))
    ap.add_argument("--district", default=None)
    ap.add_argument("--cell", type=float, default=None)
    ap.add_argument("--out", default="out_real")
    args = ap.parse_args(argv)

    base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = args.config if os.path.isabs(args.config) else os.path.join(base, args.config)
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(base, args.out)

    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = ProjectConfig.from_yaml(fh.read())
    aoi = cfg.raw["project"]["area_of_interest"]
    district = args.district or aoi.get("district") or "长宁区"
    if district in ("全市", "all", "ALL"):
        district = None
    cell = float(args.cell or aoi.get("cell_m") or 100)
    radius = float(aoi.get("radius_m") or 500)
    share = float(aoi.get("obs_share") or 0.7)
    seed = int(aoi.get("seed") or 20261117)

    hr("步骤 1 / 5  读取真实地理数据")
    print("数据源：")
    print("  村界    F:\\上海师大\\各种地理数据\\2024全国村级行政边界")
    print("  路网    F:\\上海师大\\各种地理数据\\2024年道路数据（分城市*上海市）")
    print("  土地利用 F:\\上海师大\\各种地理数据\\2026省级土地利用（上海市）")
    print("可用区县：%s" % "、".join("%s(%d)" % (d, n) for d, n in list_districts()))
    t0 = time.perf_counter()
    ds, rep = build_district_dataset(district, cell_m=cell, radius_m=radius,
                                     obs_share=share, seed=seed)
    print("\n%s：%d 个评估单元 / %d 条成交 / 用时 %.1fs"
          % (district or "上海全市", ds.n_units, ds.n_obs(), time.perf_counter() - t0))
    for n in rep.notes:
        print("  *", n)

    hr("步骤 2 / 5  执行因子 DAG（真实路网最短路）")
    engine = FactorEngine(cfg, ds)
    t = time.perf_counter()
    r = engine.run(progress=lambda c, hit, s: print("  %-18s %s  %.2fs"
                                                    % (c, "命中缓存" if hit else "计算", s)))
    print("\n%d 个因子，缓存命中 %d，用时 %.1fs" % (len(r.runs), r.n_cache_hit, time.perf_counter() - t))

    hr("步骤 3 / 5  模型训练与空间分块交叉验证")
    feats = list(cfg.model["features"])

    # 因子有效性检查：若 96% 以上的单元取值相同，这个因子实际上是个"某区哑变量"，
    # 放进回归会把区县效应伪装成设施效应（全市跑时会直接把空间块 CV 打成负数）。
    keep_feats, dropped = [], []
    for c in feats:
        v = ds.attrs.get(c)
        if v is None:
            dropped.append((c, "未计算"))
            continue
        lo, hi = np.percentile(v, 2), np.percentile(v, 98)
        if not np.isfinite(lo) or not np.isfinite(hi) or abs(hi - lo) < 1e-12:
            dropped.append((c, "取值几乎恒定（%.1f%% 相同）" % 96.0))
        else:
            keep_feats.append(c)
    if dropped:
        print("\n自动剔除 %d 个无效因子：" % len(dropped))
        for c, why in dropped:
            print("  - %-16s %s" % (c, why))
    feats = keep_feats
    X_all = ds.design_matrix(feats)
    obs = ds.obs
    X, y = X_all[obs.unit_idx], obs.unit_price
    k = int((cfg.model.get("cv") or {}).get("spatial_folds", 5))
    bx = ds.units.x[obs.unit_idx]
    span = (bx.max() - bx.min()) or 1.0
    block = np.minimum(((bx - bx.min()) / span * k).astype(int), k - 1)
    bundle = fit_and_evaluate(X, y, feats, block, cfg.model)
    m = bundle.ols
    print("样本 %d，因子 %d" % (y.size, len(feats)))
    print("训练 R²=%.4f  RMSE(log)=%.4f" % (bundle.train_metrics["r2"], bundle.train_metrics["rmse_log"]))
    print("随机 CV R²=%.4f  空间块 CV R²=%.4f（误差高 %.1f%%）"
          % (bundle.cv_random["r2"], bundle.cv_spatial["r2"],
             (bundle.cv_spatial["rmse_log"] / bundle.cv_random["rmse_log"] - 1) * 100))
    print("\n系数：")
    for row in m.rows():
        if row[0] == "常数项":
            continue
        print("  %-20s %+10.5f  t=%7.2f  p=%.3f %s" % (row[0], float(row[1]), float(row[3]), float(row[4]), row[5]))

    hr("步骤 4 / 5  批量估值与比率研究")
    pred = np.column_stack([np.ones(ds.n_units), X_all]) @ m.coef
    est = np.exp(pred)
    rng = np.random.default_rng(seed + 1)
    sims = np.empty((200, ds.n_units))
    for b in range(200):
        sims[b] = np.exp(pred + rng.choice(bundle.resid_log, ds.n_units, replace=True))
    lo, mid, hi = np.percentile(sims, [10, 50, 90], axis=0)
    print("估值中位 %.0f 元/㎡（区间 %.0f-%.0f）" % (np.median(est), np.median(lo), np.median(hi)))
    ratio = ratio_study(np.exp(bundle.oof_log), y,
                        cod_max=float(cfg.valuation.get("cod_max", 15)),
                        prd_range=tuple(cfg.valuation.get("prd_range", [0.98, 1.03])))
    print("比率研究：中位比率 %.3f  COD=%.1f（%s）  PRD=%.3f（%s）"
          % (ratio["median_ratio"], ratio["cod"], "通过" if ratio["cod_ok"] else "未通过",
             ratio["prd"], "通过" if ratio["prd_ok"] else "未通过"))

    hr("步骤 5 / 5  空间诊断与成果输出")
    moran = morans_i(bundle.resid_log, ds.units.x[obs.unit_idx], ds.units.y[obs.unit_idx],
                     k=6, n_perm=499, seed=seed)
    print("残差 Moran's I=%.4f（p=%.4f）" % (moran.i, moran.p))
    print(moran.verdict())
    dist = district_summary(ds.units.admin_code[obs.unit_idx],
                            bundle.resid_log, threshold=1.5)
    flagged = [d for d in dist if d[3] != "无明显偏离"]
    print("失配街道：%d / %d 个" % (len(flagged), len(dist)))
    for d in flagged[:8]:
        print("  %-12s 残差均值 %+.3f  %s" % (d[0], d[1], d[3]))

    os.makedirs(out_dir, exist_ok=True)
    import pandas as pd

    run_id = "REAL-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    xlsx = write_workbook(os.path.join(out_dir, "真实数据估值结果.xlsx"), {
        "估值明细": pd.DataFrame({
            "单元编号": ds.units.unit_id,
            "街道": ds.units.admin_code,
            "X": np.round(ds.units.x, 1), "Y": np.round(ds.units.y, 1),
            "面积_m2": np.round(ds.units.area, 0),
            "估值单价_中位": np.round(est, 2),
            "P10": np.round(lo, 2), "P90": np.round(hi, 2),
        }),
        "因子长表": engine.to_long_table(run_id),
        "模型系数": pd.DataFrame(m.rows(), columns=["变量", "系数", "标准误", "t", "p", "显著性"]),
        "共线性": pd.DataFrame(bundle.vif, columns=["变量", "R2_其余", "VIF"]),
        "精度对比": pd.DataFrame([
            ["训练集"] + [bundle.train_metrics[x] for x in ("r2", "rmse_log", "mape")],
            ["随机CV"] + [bundle.cv_random[x] for x in ("r2", "rmse_log", "mape")],
            ["空间块CV"] + [bundle.cv_spatial[x] for x in ("r2", "rmse_log", "mape")],
        ], columns=["口径", "R2", "RMSE_log", "MAPE"]),
        "空间诊断": pd.DataFrame([["Moran's I", moran.i], ["p", moran.p],
                                ["结论", moran.verdict()]], columns=["指标", "值"]),
    })

    resid_all = np.full(ds.n_units, np.nan)
    resid_all[obs.unit_idx] = bundle.resid_log
    png = residual_map_png(os.path.join(out_dir, "真实数据残差图.png"),
                           bundle.resid_log, ds.units.x[obs.unit_idx], ds.units.y[obs.unit_idx],
                           ds.grid.cell)

    print("\n产物：")
    for p in (xlsx, png):
        print("  %-28s %7.1f KB" % (os.path.basename(p), os.path.getsize(p) / 1024))
    print("\n总耗时 %.1fs" % (time.perf_counter() - t0))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
