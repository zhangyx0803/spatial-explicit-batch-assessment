# -*- coding: utf-8 -*-
"""命令行入口：一键跑通"因子计算 -> 模型训练 -> 批量估值 -> 空间诊断 -> 报告输出"。

用法：
    python run_demo.py                       # 用 config/factors.yaml，产物写入 out/
    python run_demo.py --out out_run2        # 指定输出目录
    python run_demo.py --config my.yaml      # 指定配置文件
    python run_demo.py --only-check          # 只校验配置，不算
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

from seba import __version__ as ENGINE_VERSION
from seba.config import ProjectConfig
from seba.diagnosis import district_summary, morans_i, residual_map_png
from seba.engine import FactorEngine
from seba.grid import build_test_dataset
from seba.ratios import ratio_study
from seba.report import write_calibration_report, write_workbook
from seba.stats import fit_and_evaluate

def _hr(title: str = "") -> None:
    print("\n" + "=" * 74)
    if title:
        print(title)
        print("=" * 74)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="空间显式批量评估工作台（版本）")
    ap.add_argument("--config", default=os.path.join("config", "factors.yaml"))
    ap.add_argument("--out", default="out")
    ap.add_argument("--only-check", action="store_true", help="只校验配置")
    args = ap.parse_args(argv)

    base = os.path.dirname(os.path.abspath(__file__))
    cfg_path = args.config if os.path.isabs(args.config) else os.path.join(base, args.config)
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(base, args.out)
    os.makedirs(out_dir, exist_ok=True)

    t_start = time.perf_counter()
    _hr("步骤 1 / 6  解析并校验声明式配置")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = ProjectConfig.from_yaml(fh.read())
    order = cfg.topological_order()
    print("工程：%s" % cfg.name)
    print("图层：%d 个；因子：%d 个" % (len(cfg.layers), len(cfg.factors)))
    print("DAG 拓扑序：%s" % " -> ".join(order[:6]) + (" ..." if len(order) > 6 else ""))
    dep = cfg.dependencies()
    edges = [(d, c) for c, ds in dep.items() for d in ds]
    print("依赖边：%s" % ("、".join("%s->%s" % e for e in edges) if edges else "无"))
    if args.only_check:
        print("\n配置校验通过。")
        return 0

    _hr("步骤 2 / 6  构建内置测试场景与盲测交易库")
    aoi = cfg.raw["project"]["area_of_interest"]
    scene = build_test_dataset(
        seed=int(aoi.get("seed", 20261117)),
        nx=int(aoi.get("nx", 40)),
        ny=int(aoi.get("ny", 40)),
        cell=float(aoi.get("cell_m", 250)),
    )
    ds = scene.dataset
    meta = ds.layers["road_net"].aux_meta
    print("单元 %d 个（%dx%d，格网 %.0f m）" % (ds.n_units, ds.grid.nx, ds.grid.ny, ds.grid.cell))
    print("成交样本 %d 条，价格类型 %s" % (ds.n_obs(), "/".join(sorted(set(ds.obs.price_type.tolist())))))
    print(
        "路网：节点 %d，连通分量 %d，最大分量占比 %.1f%%，悬挂节点 %d，单向边占比 %.1f%%"
        % (
            int(ds.layers["road_net"].nodes.shape[0]),
            int(meta["n_components"]),
            meta["largest_component_share"] * 100,
            int(meta["n_deadend_nodes"]),
            meta["oneway_share"] * 100,
        )
    )
    print("盲测设定：%s" % ", ".join("%s=%s" % (k, v) for k, v in scene.truth.items()))

    _hr("步骤 3 / 6  执行因子 DAG")
    engine = FactorEngine(cfg, ds)
    t0 = time.perf_counter()
    rep = engine.run(progress=lambda c, hit, s: print("  %-22s %s  %.3fs" % (c, "命中缓存" if hit else "计算", s)))
    print(
        "\n因子执行完成：%d 个，缓存命中 %d 个，总耗时 %.2fs"
        % (len(rep.runs), rep.n_cache_hit, time.perf_counter() - t0)
    )

    # ---- 模型 ----
    _hr("步骤 4 / 6  模型训练与空间分块交叉验证")
    feats = list(cfg.model.get("features") or [f.code for f in cfg.factors])
    X_all = ds.design_matrix(feats)          # (n_units, p)：批量估值用
    obs = ds.obs
    X = X_all[obs.unit_idx]                  # (n_obs, p)：建模用
    y = obs.unit_price
    # 空间分块：沿 x 方向切成 K 条连续条带（整块留出，块内不拆）
    k_blocks = int((cfg.model.get("cv") or {}).get("spatial_folds", 5))
    bx = ds.units.ix[obs.unit_idx]
    block = np.minimum((bx * k_blocks) // ds.grid.nx, k_blocks - 1)

    bundle = fit_and_evaluate(X, y, feats, block, cfg.model)
    ols = bundle.ols
    print("样本 %d，特征 %d，自由度 %d" % (y.size, len(feats), ols.dof))
    print(
        "训练：R²=%.4f，RMSE(log)=%.4f，MAPE=%.2f%%"
        % (bundle.train_metrics["r2"], bundle.train_metrics["rmse_log"], bundle.train_metrics["mape"])
    )
    print(
        "随机 %d 折 CV ：R²=%.4f，RMSE(log)=%.4f，MAPE=%.2f%%"
        % (
            int((cfg.model.get("cv") or {}).get("random_folds", 5)),
            bundle.cv_random["r2"], bundle.cv_random["rmse_log"], bundle.cv_random["mape"],
        )
    )
    print(
        "空间 %d 块 CV ：R²=%.4f，RMSE(log)=%.4f，MAPE=%.2f%%"
        % (k_blocks, bundle.cv_spatial["r2"], bundle.cv_spatial["rmse_log"], bundle.cv_spatial["mape"])
    )
    inflate = (1.0 - bundle.cv_random["rmse_log"] / bundle.cv_spatial["rmse_log"]) * 100
    print("-> 随机 CV 的 RMSE 比空间块 CV 低 %.1f%%，即随机 K 折高估了精度（空间自相关）" % inflate)

    # 安慰剂检验
    placebo = [c for c in feats if c.startswith("b_placebo")]
    if placebo:
        names = ols.names
        print("\n安慰剂因子检验（应接近 0）：")
        for c in placebo:
            k = names.index(c)
            print("  %-14s 系数=%+.5f  t=%+.2f  p=%.3f" % (c, ols.coef[k], ols.t[k], ols.p[k]))

    vif_hi = [r for r in bundle.vif if float(r[2]) > float(cfg.model.get("vif_threshold", 10))]
    print("\n共线性：VIF > %s 的变量 %d 个%s" % (
        cfg.model.get("vif_threshold", 10),
        len(vif_hi),
        ("：" + "、".join("%s(%.1f)" % (r[0], float(r[2])) for r in vif_hi)) if vif_hi else "，无需剔除",
    ))

    # ---- 批量估值 ----
    _hr("步骤 5 / 6  批量估值与不确定性")
    pred_log = np.column_stack([np.ones(ds.n_units), X_all]) @ ols.coef
    sm = ols.smearing
    # 中位口径：exp(x'b) 即条件中位数，比率研究按此口径（IAAO 以中位数为基准）
    est_median = np.exp(pred_log)
    # 均值口径：Duan smearing 修正后的期望值，用于"期望总价值"一类的汇报口径
    est_mean = est_median * sm

    val_cfg = cfg.valuation or {}
    n_boot = int(val_cfg.get("interval_bootstrap", 200))
    levels = [float(x) for x in (val_cfg.get("levels") or [10, 50, 90])]
    rng = np.random.default_rng(int(cfg.model.get("seed", 0)))
    resid = bundle.resid_log
    sims = np.empty((n_boot, ds.n_units), dtype=float)
    for b in range(n_boot):
        eps = rng.choice(resid, size=ds.n_units, replace=True)
        sims[b] = np.exp(pred_log + eps)
    lo, mid, hi = np.percentile(sims, levels, axis=0)
    print("中位口径点估计：均值 %.0f 元/m²，中位 %.0f 元/m²" % (est_median.mean(), np.median(est_median)))
    print("均值口径（smearing=%.4f）：均值 %.0f 元/m²" % (sm, est_mean.mean()))
    print(
        "P%.0f/%.0f/%.0f 区间平均值：%.0f / %.0f / %.0f 元/m²"
        % (levels[0], levels[1], levels[2], lo.mean(), mid.mean(), hi.mean())
    )
    print("两者差 %.1f%%：比率研究取中位口径，期望值汇报取均值口径，不可混用"
          % ((sm - 1.0) * 100))

    # 比率研究（用空间块 CV 的留块预测，样本外口径）
    oof = bundle.oof_log
    est_oof = np.exp(oof)
    ratio = ratio_study(
        est_oof,
        y,
        cod_max=float(val_cfg.get("cod_max", 15)),
        prd_range=tuple(val_cfg.get("prd_range", [0.98, 1.03])),
    )
    print(
        "\n比率研究（留块预测，样本外）：n=%d，中位比率 %.4f，COD=%.2f（≤%.0f %s），PRD=%.4f（%s）"
        % (
            int(ratio["n"]), ratio["median_ratio"], ratio["cod"], ratio["cod_max"],
            "通过" if ratio["cod_ok"] else "未通过", ratio["prd"],
            "通过" if ratio["prd_ok"] else "未通过",
        )
    )

    # ---- 空间诊断 ----
    _hr("步骤 6 / 6  空间误差诊断与成果输出")
    mp = int((cfg.diagnosis or {}).get("permutations", 499))
    moran = morans_i(bundle.resid_log, ds.units.x[obs.unit_idx], ds.units.y[obs.unit_idx],
                     k=6, n_perm=mp, seed=int(cfg.model.get("seed", 0)))
    print("残差 Moran's I = %.4f（E[I]=%.4f，z=%.2f，p=%.4f，%d 次置换）"
          % (moran.i, moran.e_i, moran.z, moran.p, moran.n_perm))
    print("结论：%s" % moran.verdict())

    districts = district_summary(
        ds.units.admin_code[obs.unit_idx], bundle.resid_log,
        threshold=float((cfg.diagnosis or {}).get("district_t_threshold", 1.5)),
    )
    flagged = [d for d in districts if d[3] != "无明显偏离"]
    print("失配板块：%d 个%s" % (
        len(flagged),
        ("（" + "、".join("%s %s" % (d[0], d[3]) for d in flagged[:5]) + ("..." if len(flagged) > 5 else "") + "）") if flagged else "",
    ))

    # ---- 落盘 ----
    run_id = "RUN-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(out_dir, exist_ok=True)

    import pandas as pd

    long_df = engine.to_long_table(run_id)
    val_df = pd.DataFrame(
        {
            "unit_id": ds.units.unit_id,
            "ix": ds.units.ix,
            "iy": ds.units.iy,
            "area_m2": ds.units.area,
            "admin_code": ds.units.admin_code,
            "est_unit_price_median": np.round(est_median, 2),
            "est_unit_price_mean": np.round(est_mean, 2),
            "p_low": np.round(lo, 2),
            "p_mid": np.round(mid, 2),
            "p_high": np.round(hi, 2),
            "interval_width_ratio": np.round((hi - lo) / np.maximum(est_median, 1e-9), 4),
        }
    )
    obs_df = pd.DataFrame(
        {
            "unit_id": ds.units.unit_id[obs.unit_idx],
            "deal_date": obs.deal_date,
            "price_type": obs.price_type,
            "sale_unit_price": np.round(y, 2),
            "est_unit_price": np.round(est_oof, 2),
            "ratio": np.round(est_oof / y, 4),
            "resid_log": np.round(bundle.resid_log, 5),
        }
    )
    coef_df = pd.DataFrame(
        ols.rows(),
        columns=["变量", "系数", "标准误", "t", "p", "显著性"],
    )
    vif_df = pd.DataFrame(bundle.vif, columns=["变量", "R2_rest", "VIF"])
    cv_df = pd.DataFrame(
        [
            ["训练集（样本内）"] + [bundle.train_metrics[k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
            ["随机 K 折 CV"] + [bundle.cv_random[k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
            ["空间分块 CV"] + [bundle.cv_spatial[k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
        ],
        columns=["口径", "R2", "RMSE_log", "MAE_log", "MAPE", "MedAPE"],
    )
    run_df = pd.DataFrame(rep.as_rows(), columns=["因子", "算子", "缓存", "耗时(s)", "输出"])
    diag_df = pd.DataFrame(
        [
            ["Moran's I", moran.i],
            ["E[I]", moran.e_i],
            ["sd(perm)", moran.sd],
            ["z", moran.z],
            ["p", moran.p],
            ["置换次数", moran.n_perm],
            ["结论", moran.verdict()],
        ],
        columns=["指标", "值"],
    )

    xlsx = write_workbook(
        os.path.join(out_dir, "valuation_result.xlsx"),
        {
            "估值明细": val_df,
            "因子长表": long_df,
            "模型系数": coef_df,
            "共线性": vif_df,
            "精度对比": cv_df,
            "空间诊断": diag_df,
            "因子执行": run_df,
            "成交校验": obs_df,
        },
    )

    png = residual_map_png(
        os.path.join(out_dir, "residual_map.png"),
        bundle.resid_log,
        ds.units.x[obs.unit_idx],
        ds.units.y[obs.unit_idx],
        ds.grid.cell,
    )

    factor_rows = []
    for code in feats:
        f = cfg.factor(code)
        arr = ds.attrs[code]
        factor_rows.append(
            [code, f.op, (f.note or "")[:24], "%.4g" % float(np.mean(arr)), "%.4g" % float(np.std(arr))]
        )

    docx_path = write_calibration_report(
        os.path.join(out_dir, "calibration_report.docx"),
        {
            "project_name": ds.project_name,
            "crs": ds.crs,
            "n_units": ds.n_units,
            "n_obs": ds.n_obs(),
            "asof_date": ds.units.asof_date,
            "cell_area": ds.grid.area,
            "snap_failed": rep.snap_failures.get("road_net", 0.0),
            "snap_mean_dist": rep.snap_mean_dist.get("road_net", 0.0),
            "factor_rows": factor_rows,
            "smearing": ols.smearing,
            "coef_rows": ols.rows(),
            "vif_threshold": cfg.model.get("vif_threshold", 10),
            "vif_rows": bundle.vif,
            "metric_rows": cv_df.values.tolist(),
            "ratio": ratio,
            "moran": moran,
            "district_rows": [[d[0], "%.4f" % d[1], d[2], d[3]] for d in districts[:12]],
            "run_id": run_id,
            "config_fingerprint": cfg.fingerprint(),
            "seed": cfg.model.get("seed", 0),
            "data_version": "demo-2025-06-30 / 合成",
            "engine_version": ENGINE_VERSION,
        },
    )

    with open(os.path.join(out_dir, "run_log.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "run_id": run_id,
                "config_fingerprint": cfg.fingerprint(),
                "engine_version": ENGINE_VERSION,
                "elapsed_seconds": round(time.perf_counter() - t_start, 2),
                "factors": [
                    {"code": r.code, "op": r.op, "cache_hit": r.cache_hit, "seconds": round(r.seconds, 3),
                     "outputs": r.outputs}
                    for r in rep.runs
                ],
                "dependency_edges": [list(e) for e in rep.dependency_edges],
                "metrics": {
                    "train": bundle.train_metrics,
                    "cv_random": bundle.cv_random,
                    "cv_spatial": bundle.cv_spatial,
                },
                "ratio_study": ratio,
                "moran": {"i": moran.i, "p": moran.p, "z": moran.z, "n_perm": moran.n_perm},
                "snap_failures": rep.snap_failures,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )

    print("\n产物已写入：%s" % out_dir)
    for name in ("valuation_result.xlsx", "calibration_report.docx", "residual_map.png", "run_log.json"):
        p = os.path.join(out_dir, name)
        print("  %-24s %8.1f KB" % (name, os.path.getsize(p) / 1024.0))
    print("\n总耗时 %.1fs" % (time.perf_counter() - t_start))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
