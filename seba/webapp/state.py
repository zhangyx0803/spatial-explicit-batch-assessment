# -*- coding: utf-8 -*-
"""Web 版运行态：场景、因子引擎、模型拟合三层的缓存与重建。

三个入口：
    build_demo()      用内置演示区
    import_data(spec) 用用户导入的 CSV
    update_factors()  改因子参数 / 启用状态后重算
场景与因子只在数据变化时重算，改模型特征只重跑模型层。
"""

from __future__ import annotations

import copy
import datetime as dt
import math
import os
import time
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..config import ProjectConfig, _validate_factor
from ..diagnosis import district_summary, morans_i, residual_map_png
from ..engine import FactorEngine
from ..grid import build_demo_dataset
from ..importer import ImportError2, build_dataset
from ..labels import FACTOR_CN, LAYER_TYPE_CN, TEMPLATES, catalog, factor_name, op_name
from ..ratios import ratio_study
from ..report import write_calibration_report, write_workbook
from ..stats import fit_and_evaluate

__all__ = ["AppState"]

# 演示场景专用的中间因子：不进特征池
_INTERMEDIATE = ("net_cbd_dist", "acc_cbd_time_turn")


def _num(a, nd: int = 4):
    out = []
    for v in np.asarray(a, dtype=float).ravel():
        out.append(None if not math.isfinite(float(v)) else round(float(v), nd))
    return out


class _MoranView:
    def __init__(self, d: Dict):
        self.i, self.e_i, self.sd = d["i"], d["e"], d["sd"]
        self.z, self.p, self.n_perm = d["z"], d["p"], d["n_perm"]
        self._v = d["verdict"]

    def verdict(self) -> str:
        return self._v


_USE_HINT = (
    ("商业/工业", ("商业/工业", "商业工业", "工业地块")),
    ("学校", ("幼儿园", "小学", "中学", "学校", "大学", "学院", "附中", "附小")),
    ("公园", ("公园", "绿地", "植物园", "动物园")),
    ("医院", ("医院", "卫生院", "卫生中心", "保健院")),
    ("商业", ("商业", "广场", "商场", "大厦", "百货", "商城")),
    ("办公", ("办事处", "街道办", "政府", "委员会", "管理中心", "行政")),
    ("产业", ("公司", "集团", "厂", "基地", "园区", "产业园", "仓库", "工业", "厂房", "车间", "仓储", "物流")),
    ("交通", ("车站", "地铁", "机场", "码头", "车辆段", "停车场")),
    ("文体", ("体育", "文化", "图书馆", "剧院", "音乐厅", "美术馆")),
    ("宗教", ("寺", "庙", "教堂", "道观")),
)


def _use_detail(name: str, use_type: str) -> str:
    """把“非住宅”细化为学校 / 公园 / 商业 / 办公 等，便于阅读。"""
    if str(use_type) == "住宅":
        return "住宅"
    n = str(name or "")
    for label, keys in _USE_HINT:
        if any(k in n for k in keys):
            return label
    return "非住宅"


class AppState:
    def __init__(self, cfg_path: str, dataset=None, notes=None, source: str = "demo",
                 prebuilt: bool = False, districts_dir: str = None):
        self.cfg_path = cfg_path
        with open(cfg_path, "r", encoding="utf-8") as fh:
            self.cfg = ProjectConfig.from_yaml(fh.read())
        self._cfg_template = copy.deepcopy(self.cfg)
        self._demo_spec = copy.deepcopy(self.cfg.raw)
        self.source = source
        self.prebuilt = bool(prebuilt)
        self.import_notes: List[str] = list(notes or [])
        self.run_id = "RUN-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.districts_dir = districts_dir
        self.districts: List[Dict] = []
        self.current = None

        t0 = time.perf_counter()
        if districts_dir:
            # 多区模式：先扫描可用区，不加载任何数据，等用户选
            self.districts = self._scan_districts(districts_dir)
            self.ds = None
            self.load_seconds = 0.0
            return
        if dataset is not None:
            self._activate(dataset)
            self.load_seconds = time.perf_counter() - t0
            return

        scene = build_demo_dataset(
            seed=int((self.cfg.raw["project"].get("area_of_interest") or {}).get("seed", 20261117)),
            nx=int((self.cfg.raw["project"].get("area_of_interest") or {}).get("nx", 40)),
            ny=int((self.cfg.raw["project"].get("area_of_interest") or {}).get("ny", 40)),
            cell=float((self.cfg.raw["project"].get("area_of_interest") or {}).get("cell_m", 250)),
        )
        self._activate(scene.dataset)
        self.load_seconds = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # 多区：扫描、切换
    # ------------------------------------------------------------------
    @staticmethod
    def _scan_districts(d: str) -> List[Dict]:
        import json

        idx = os.path.join(d, "_index.json")
        if os.path.exists(idx):
            try:
                with open(idx, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass
        out = []
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".bundle"):
                out.append({"name": fn[:-7], "units": 0, "obs": 0,
                            "r2": None, "mb": round(os.path.getsize(os.path.join(d, fn)) / 1048576, 2)})
        return out

    def switch_district(self, name: str) -> Dict:
        from ..bundle import load_bundle

        path = os.path.join(self.districts_dir or "", "%s.bundle" % name)
        if not os.path.exists(path):
            raise ValueError("找不到区数据：%s" % name)
        ds, notes, extra = load_bundle(path)
        self.prebuilt = True
        self.import_notes = list(notes or [])
        self.current = name
        self.run_id = "RUN-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        t0 = time.perf_counter()
        self._activate(ds)
        self.load_seconds = time.perf_counter() - t0
        return self.bootstrap()

    # ------------------------------------------------------------------
    # 激活一个数据集：跑因子、定特征池、拟合
    # ------------------------------------------------------------------
    def _activate(self, ds) -> None:
        self.ds = ds
        self.engine = FactorEngine(self.cfg, ds)
        # 数据包里因子已经算好，且网络几何被剥掉，不能再跑一遍 DAG
        if getattr(self, "prebuilt", False) and ds.attrs:
            self.rep = None
        else:
            self.rep = self.engine.run()

        all_codes = [f.code for f in self.cfg.factors]
        self.pool = [c for c in all_codes if c not in _INTERMEDIATE and c in ds.attrs]
        wanted = [c for c in (self.cfg.model.get("features") or []) if c in self.pool]
        if not wanted:
            wanted = list(self.pool)
        self.default_features = wanted
        self._cache: Dict[tuple, Dict] = {}
        self.features = list(wanted)
        self.result = self.fit(self.features)

    def _recompute(self) -> None:
        """就地重建引擎与结果（配置变了但数据没变）。"""
        self.engine = FactorEngine(self.cfg, self.ds)
        self.rep = self.engine.run()
        all_codes = [f.code for f in self.cfg.factors]
        self.pool = [c for c in all_codes if c not in _INTERMEDIATE and c in self.ds.attrs]
        keep = [c for c in self.features if c in self.pool] or list(self.pool)
        self._cache = {}
        self.features = keep
        self.result = self.fit(keep)

    # ------------------------------------------------------------------
    # 模型层
    # ------------------------------------------------------------------
    def _block(self) -> np.ndarray:
        obs = self.ds.obs
        k = int((self.cfg.model.get("cv") or {}).get("spatial_folds", 5))
        bx = self.ds.units.x[obs.unit_idx]
        span = (bx.max() - bx.min()) or 1.0
        return np.minimum(((bx - bx.min()) / span * k).astype(int), k - 1)

    def fit(self, features: Sequence[str]) -> Dict:
        feats = [f for f in features if f in self.ds.attrs]
        # 剔除几乎恒定的因子（它们会退化成区县哑变量）
        good = []
        for f in feats:
            v = self.ds.attrs[f]
            lo, hi = np.percentile(v, 2), np.percentile(v, 98)
            if np.isfinite(lo) and np.isfinite(hi) and abs(hi - lo) > 1e-12:
                good.append(f)
        feats = good
        if not feats:
            raise ValueError("至少要选择一个有效因子（当前所选因子取值几乎恒定）")
        key = tuple(sorted(feats))
        if key in self._cache:
            return self._cache[key]

        obs = self.ds.obs
        X_all = self.ds.design_matrix(feats)
        X = X_all[obs.unit_idx]
        y = obs.unit_price
        bundle = fit_and_evaluate(X, y, feats, self._block(), self.cfg.model)
        ols = bundle.ols

        pred_log = np.column_stack([np.ones(self.ds.n_units), X_all]) @ ols.coef
        sm = ols.smearing
        est_median = np.exp(pred_log)
        est_mean = est_median * sm

        val_cfg = self.cfg.valuation or {}
        n_boot = int(val_cfg.get("interval_bootstrap", 200))
        levels = [float(v) for v in (val_cfg.get("levels") or [10, 50, 90])]
        rng = np.random.default_rng(int(self.cfg.model.get("seed", 0)))
        sims = np.empty((n_boot, self.ds.n_units), dtype=float)
        for b in range(n_boot):
            eps = rng.choice(bundle.resid_log, size=self.ds.n_units, replace=True)
            sims[b] = np.exp(pred_log + eps)
        lo, mid, hi = np.percentile(sims, levels, axis=0)

        # 非住宅单元（公园、商业、学校、办公等）不输出估值
        _ut = getattr(self.ds.units, "use_type", None)
        if _ut is not None:
            _mask = np.asarray(_ut).astype(str) != "住宅"
            if _mask.any():
                est_median = np.where(_mask, np.nan, est_median)
                est_mean = np.where(_mask, np.nan, est_mean)
                lo = np.where(_mask, np.nan, lo)
                mid = np.where(_mask, np.nan, mid)
                hi = np.where(_mask, np.nan, hi)

        est_oof = np.exp(bundle.oof_log)
        ratio = ratio_study(
            est_oof, y,
            cod_max=float(val_cfg.get("cod_max", 15)),
            prd_range=tuple(val_cfg.get("prd_range", [0.98, 1.03])),
        )

        mp = int((self.cfg.diagnosis or {}).get("permutations", 499))
        moran = morans_i(
            bundle.resid_log,
            self.ds.units.x[obs.unit_idx],
            self.ds.units.y[obs.unit_idx],
            k=6, n_perm=mp,
            seed=int(self.cfg.model.get("seed", 0)),
        )
        districts = district_summary(
            self.ds.units.admin_code[obs.unit_idx],
            bundle.resid_log,
            threshold=float((self.cfg.diagnosis or {}).get("district_t_threshold", 1.5)),
        )

        # ---- 分区校准：按街道估偏差，收缩后修正估值 ----
        from ..stats import calibrate_block

        calib = calibrate_block(
            self.ds.units.admin_code[obs.unit_idx], bundle.resid_log,
            k=float((self.cfg.diagnosis or {}).get("calib_shrink_k", 5.0)),
        )
        bias_unit = np.array([calib.bias_of(a) for a in self.ds.units.admin_code],
                             dtype=float)
        est_cal = np.exp(pred_log + bias_unit)
        if _ut is not None:
            est_cal = np.where(np.asarray(_ut).astype(str) != "住宅", np.nan, est_cal)
        grade_unit = [calib.grade_of(a) for a in self.ds.units.admin_code]

        resid_unit = np.full(self.ds.n_units, np.nan)
        resid_unit[obs.unit_idx] = bundle.resid_log

        # 实际成交单价（无成交单元为 NaN），用于地图与悬停展示
        obs_price_unit = np.full(self.ds.n_units, np.nan)
        obs_price_unit[obs.unit_idx] = np.asarray(obs.unit_price, dtype=float)

        names = {c: factor_name(c, self.cfg.factor(c).note) for c in feats}
        res = {
            "features": feats,
            "names": names,
            "metrics": {
                "train": bundle.train_metrics,
                "cv_random": bundle.cv_random,
                "cv_spatial": bundle.cv_spatial,
                "smearing": sm, "dof": ols.dof, "n": int(y.size),
            },
            "coef": [[names.get(r[0], r[0])] + list(r[1:]) for r in ols.rows()],
            "vif": [[names.get(r[0], r[0]), float(r[1]), float(r[2])] for r in bundle.vif],
            "ratio": {k: (None if not isinstance(v, float) or not math.isfinite(v) else v) for k, v in ratio.items()},
            "moran": {
                "i": moran.i, "e": moran.e_i, "sd": moran.sd, "z": moran.z,
                "p": moran.p, "n_perm": moran.n_perm, "verdict": moran.verdict(),
            },
            "districts": [{"code": d[0], "mean": d[1], "n": d[2], "tag": d[3]} for d in districts],
            "calibration": {
                "k": calib.k,
                "global_mean": round(calib.global_mean, 4),
                "groups": calib.table(),
            },
            "grades": grade_unit,
            "arrays": {
                "est_median": _num(est_median, 1),
                "est_cal": _num(est_cal, 1),
                "est_mean": _num(est_mean, 1),
                "p_low": _num(lo, 1),
                "p_mid": _num(mid, 1),
                "p_high": _num(hi, 1),
                "resid": _num(resid_unit, 4),
                "obs_price": _num(obs_price_unit, 1),
            },
        }
        self._cache[key] = res
        return res

    # ------------------------------------------------------------------
    # 概况
    # ------------------------------------------------------------------
    def factor_stats(self) -> List[Dict]:
        rows = []
        for code in self.pool:
            f = self.cfg.factor(code)
            values = self.ds.attrs[code]
            import numpy as _np
            lo, hi = _np.percentile(values, 2), _np.percentile(values, 98)
            rows.append({
                "code": code,
                "name": factor_name(code, f.note),
                "op": f.op,
                "op_name": op_name(f.op),
                "note": f.note or "",
                "params": copy.deepcopy(f.params),
                "inputs": dict(f.inputs),
                "mean": float(np.mean(values)),
                "sd": float(np.std(values)),
                "selected": code in self.features,
                "editable": code not in FACTOR_CN,
                "invalid": bool(lo >= hi),
            })
        return rows

    def layer_list(self) -> List[Dict]:
        out = []
        for lid, spec in self.cfg.layers.items():
            lyr = self.ds.layers.get(lid)
            kind = (spec.get("type") or "").lower()
            display = (lyr.aux_meta or {}).get("display_name") if lyr else None
            out.append({
                "id": lid,
                "name": display or _layer_cn(lid, kind),
                "type": spec.get("type"),
                "type_cn": LAYER_TYPE_CN.get(kind, kind),
                "version": spec.get("version"),
                "used": bool(lyr is not None),
                "n": int(lyr.x.size) if (lyr is not None and lyr.x is not None) else None,
            })
        return out

    def _basemap_payload(self) -> Dict:
        """底图 + 点图层坐标。

        道路/水体/中心地原本就在 ds.basemap 里；地铁、商业、公交、学校等
        点图层只存在 ds.layers 中，前端没有坐标就画不出来，所以在这里统一
        打包成 {id, name, xy}，供“数据图层”勾选叠加。
        """
        bm = dict(getattr(self.ds, "basemap", {}) or {})
        pts = []
        for lid, lyr in (getattr(self.ds, "layers", {}) or {}).items():
            if getattr(lyr, "layer_type", "") != "point":
                continue
            xs = getattr(lyr, "x", None)
            ys = getattr(lyr, "y", None)
            if xs is None or ys is None or len(xs) == 0:
                continue
            name = ((lyr.aux_meta or {}).get("display_name")
                    or _layer_cn(lid, "point"))
            pts.append({
                "id": lid,
                "name": str(name),
                "xy": [[round(float(a), 1), round(float(b), 1)]
                       for a, b in zip(xs, ys)],
            })
        bm["points"] = pts
        return bm

    def bootstrap(self) -> Dict:
        if getattr(self, "ds", None) is None:
            return {"need_select": True, "districts": self.districts,
                    "cfg_path": os.path.basename(self.cfg_path)}
        net = self.ds.layers["road_net"]
        meta = net.aux_meta or {}
        u = self.ds.units
        # 单元用途（住宅 / 非住宅），供前端区分是否显示价格
        _ut = getattr(self.ds.units, "use_type", None)
        _utypes = ([str(x) for x in _ut] if _ut is not None
                   else ["住宅"] * self.ds.n_units)
        _unames = getattr(self.ds.units, "name", None)

        return {
            "district": getattr(self, "current", None),
            "project": {
                "name": self.ds.project_name,
                "crs": self.ds.crs,
                "nx": self.ds.grid.nx,
                "ny": self.ds.grid.ny,
                "cell": self.ds.grid.cell,
                "n_units": self.ds.n_units,
                "n_obs": self.ds.n_obs(),
                "asof_date": u.asof_date,
                "load_seconds": round(self.load_seconds, 2),
                "run_id": self.run_id,
                "config_fingerprint": self.cfg.fingerprint(),
                "engine_factors": len(self.rep.runs) if self.rep else len(self.ds.attrs),
                "cache_hits": self.rep.n_cache_hit if self.rep else 0,
                "dependencies": [list(e) for e in self.rep.dependency_edges] if self.rep else [],
                "source": self.source,
                "extent": _extent_with_basemap(u, getattr(self.ds, "basemap", {}) or {}),
            },
            "network": {
                "n_nodes": (int(net.nodes.shape[0])
                            if getattr(net, "nodes", None) is not None
                            else (int(meta["n_nodes"]) if meta.get("n_nodes") else None)),
                "n_components": (int(meta["n_components"])
                                 if meta.get("n_components") else None),
                "largest_share": (float(meta["largest_component_share"])
                                  if meta.get("largest_component_share") else None),
                "deadend": (int(meta["n_deadend_nodes"])
                            if meta.get("n_deadend_nodes") else None),
                "oneway_share": (float(meta["oneway_share"])
                                 if meta.get("oneway_share") else None),
                "snap_fail": (self.rep.snap_failures.get("road_net", 0.0)
                              if self.rep else None),
                "snap_mean_dist": (self.rep.snap_mean_dist.get("road_net", 0.0)
                                   if self.rep else None),
            },
            "catalog": catalog(),
            "factors": self.factor_stats(),
            "layers": self.layer_list(),
            "import_notes": self.import_notes,
            "units": {
                "id": u.unit_id.tolist(),
                "x": _num(u.x, 2),
                "y": _num(u.y, 2),
                "admin": u.admin_code.tolist(),
                "name": [str(x) for x in (
                    getattr(u, "name", None) if getattr(u, "name", None) is not None else u.unit_id)],
                "use_type": _utypes,
                "use_detail": [_use_detail(
                    str(u.name[i]) if getattr(u, "name", None) is not None else "",
                    _utypes[i]) for i in range(self.ds.n_units)],
                "area": _num(u.area, 0),
            },
            "has_obs": [bool(v) for v in np.isin(np.arange(self.ds.n_units), self.ds.obs.unit_idx)],
            "basemap": self._basemap_payload(),
            "result": self.result,
        }

    def field(self, code: str) -> Dict:
        if code not in self.ds.attrs:
            raise KeyError("未知因子：%s" % code)
        values = self.ds.attrs[code]
        return {
            "code": code,
            "name": factor_name(code, self.cfg.factor(code).note),
            "values": _num(values, 4),
            "min": float(np.min(values)), "max": float(np.max(values)), "mean": float(np.mean(values)),
        }

    def decompose_unit(self, idx: int, price=None, radius=1500.0, min_n=60) -> Dict:
        """价格拆解 + 个性化适配所需的数据。"""
        from ..decompose import BUYER_HINT, decompose as _dec

        # 非住宅单元（学校、公园、商业、办公等）没有住宅价格，不能做价格拆解。
        # 否则模型会拿周边住宅样本外推一个“价格”，看起来像真的。
        _ut = getattr(self.ds.units, "use_type", None)
        if _ut is not None and str(_ut[int(idx)]) != "住宅":
            _nm = ""
            _names_attr = getattr(self.ds.units, "name", None)
            if _names_attr is not None:
                _nm = str(_names_attr[int(idx)])
            return {
                "blocked": True,
                "use_type": str(_ut[int(idx)]),
                "unit_name": _nm,
                "reason": "该单元为%s用地，没有住宅价格，不参与估值与价格拆解" % str(_ut[int(idx)]),
            }

        feats = [c for c in (self.cfg.model.get("features") or []) if c in self.ds.attrs]
        if not feats:
            raise ValueError("没有可用因子")
        w = {c: 1.0 for c in feats}
        dec = _dec(self.ds, w, int(idx), asking_price=price,
                           radius=float(radius), min_n=int(min_n))
        _names = {}
        for _f in self.cfg.factors:
            _names[_f.code] = factor_name(_f.code, _f.note or "")
        items = []
        for it in dec.items:
            items.append({
                "code": it.code,
                "name": _names.get(it.code, it.name),
                "hint": BUYER_HINT.get(it.code, ""),
                "contribution": round(float(it.contribution)),
                "lo": round(float(it.lo)),
                "hi": round(float(it.hi)),
                "significant": not (it.lo <= 0 <= it.hi),
            })
        _ui = int(idx)
        _uname = ""
        try:
            _nm = getattr(self.ds.units, "name", None)
            if _nm is not None and _ui < len(_nm):
                _uname = str(_nm[_ui])
        except Exception:
            _uname = ""
        return {
            "unit_id": dec.unit_id,
            "unit_name": _uname,
            "asking_price": round(dec.asking_price),
            "base_price": round(dec.base_price),
            "model_price": round(dec.model_price),
            "unexplained": round(dec.unexplained),
            "n_samples": dec.n_samples,
            "radius": round(dec.radius, 0),
            "r2": round(dec.r2, 3),
            "bad_sign": dec.bad_sign,
            "items": items,
        }

    def unit_detail(self, idx: int) -> Dict:
        if idx < 0 or idx >= self.ds.n_units:
            raise IndexError("单元序号越界")
        u = self.ds.units
        a = self.result["arrays"]
        hit = np.nonzero(self.ds.obs.unit_idx == idx)[0]
        obs_row = None
        if hit.size:
            k = int(hit[0])
            obs_row = {
                "deal_date": str(self.ds.obs.deal_date[k]),
                "sale_unit_price": float(self.ds.obs.unit_price[k]),
            }
        return {
            "idx": idx,
            "unit_id": str(u.unit_id[idx]),
            "x": float(u.x[idx]), "y": float(u.y[idx]),
            "admin": str(u.admin_code[idx]),
            "unit_name": (str(u.name[idx]) if getattr(u, "name", None) is not None else ""),
            "use_type": (str(u.use_type[idx]) if getattr(u, "use_type", None) is not None else "住宅"),
            "use_detail": _use_detail(
                (str(u.name[idx]) if getattr(u, "name", None) is not None else ""),
                (str(u.use_type[idx]) if getattr(u, "use_type", None) is not None else "住宅")),
            "area": float(u.area[idx]),
            "population": float(u.population[idx]),
            "est_median": a["est_median"][idx],
            "est_cal": a.get("est_cal", a["est_median"])[idx],
            "grade": (self.result.get("grades") or ["unknown"] * self.ds.n_units)[idx],
            "est_mean": a["est_mean"][idx],
            "p_low": a["p_low"][idx],
            "p_high": a["p_high"][idx],
            "resid": a["resid"][idx],
            "has_obs": bool(hit.size),
            "obs": obs_row,
            "factors": [
                {"code": c, "name": factor_name(c, self.cfg.factor(c).note),
                 "value": float(self.ds.attrs[c][idx]), "selected": c in self.result["features"]}
                for c in self.pool
            ],
        }

    # ------------------------------------------------------------------
    # 数据导入 / 恢复演示
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 数据接入向导
    # ------------------------------------------------------------------
    def _upload_dir(self) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.abspath(os.path.join(here, "..", "..", "uploads"))
        os.makedirs(d, exist_ok=True)
        return d

    def intake_upload(self, files):
        """接收 base64 文件，落到 uploads/ 下。"""
        import base64 as _b64

        d = self._upload_dir()
        saved = []
        for f in files:
            name = os.path.basename(str(f.get("name") or "file.dat"))
            payload = f.get("b64") or ""
            if not payload:
                continue
            try:
                raw = _b64.b64decode(payload.split(",")[-1])
            except Exception:
                continue
            if not raw:
                continue
            with open(os.path.join(d, name), "wb") as fh:
                fh.write(raw)
            saved.append({"name": name, "path": os.path.join(d, name), "size": len(raw)})
        return {"ok": True, "dir": d, "saved": saved}

    def intake_analyze(self, paths):
        """识别文件类型与字段含义。"""
        from .. import intake as ik

        infos = []
        for p in paths:
            p = str(p)
            if not os.path.exists(p):
                continue
            infos.append(ik.inspect_file(p))
        for fi in infos:
            if fi.kind == "shp" and not fi.columns:
                fi.error = "缺少同名 .dbf 属性表，请把 .shp/.dbf/.prj 一起上传"

        ik.guess_roles(infos)
        roles = {}
        for fi in infos:
            if fi.role and not fi.error:
                cur = roles.get(fi.role)
                if cur is None or fi.n_features > cur["features"]:
                    roles[fi.role] = {"file": os.path.basename(fi.path),
                                      "features": fi.n_features,
                                      "conf": round(fi.role_conf, 3)}
        return {
            "ok": True,
            "files": [fi.to_dict() for fi in infos],
            "roles": roles,
            "role_spec": {k: {"label": v["label"], "geom": v["geom"],
                              "required": v["required"],
                              "fields": {fk: fv["label"] for fk, fv in v["fields"].items()}}
                          for k, v in ik.ROLES.items()},
        }

    def intake_sample(self):
        """用内置的上海数据跑一遍识别，让用户先看到效果再上传。"""
        from ..realdata import SOURCE

        paths = [SOURCE.get("village"), SOURCE.get("roads"), SOURCE.get("landuse")]
        return self.intake_analyze([p for p in paths if p and os.path.exists(p)])

    def intake_apply(self, body):
        """把确认后的映射写成 datasource.json，并立刻用新数据跑一遍（免重启）。"""
        import json as _json

        from .. import realdata as rd
        from ..intake import build_datasource

        mapping = body.get("mapping") or {}
        ds_cfg = build_datasource(mapping)
        ds_cfg["name"] = body.get("name") or "用户上传数据"
        if body.get("cbd_lon") and body.get("cbd_lat"):
            ds_cfg["cbd"] = [float(body["cbd_lon"]), float(body["cbd_lat"])]
        target = os.path.join(os.path.dirname(self.cfg_path), "datasource.json")
        with open(target, "w", encoding="utf-8") as fh:
            _json.dump(ds_cfg, fh, ensure_ascii=False, indent=2)

        out = {"ok": True, "saved_to": target, "datasource": ds_cfg}
        if not body.get("run", True):
            out["note"] = "配置已保存。下次启动时生效。"
            return out

        # ---- 立刻加载并运行 ----
        rd.reload_source(target)
        try:
            districts = [d for d, _ in rd.list_districts()]
        except Exception:
            districts = []
        want = body.get("district") or ""
        if want and want not in districts and districts:
            want = ""
        if not want and districts:
            want = districts[0][0] if isinstance(districts[0], (list, tuple)) else districts[0]

        ds, rep = rd.build_district_dataset(want or None)
        self.cfg = self._adapt_cfg_to(ds)
        self.cfg_path = self.cfg_path
        self._cfg_template = copy.deepcopy(self.cfg)
        self.source = "upload"
        self.import_notes = list(rep.notes)
        self._activate(ds)
        res = self.fit(list(self.cfg.model.get("features") or []))
        self.features = res["features"]
        self.result = res
        out.update({
            "note": "配置已保存，并已用你的数据跑完：%s，%d 个单元。" % (want or "全市", ds.n_units),
            "ran": True,
            "district": want,
            "n_units": ds.n_units,
            "n_obs": ds.n_obs(),
        })
        out.update(self.bootstrap())
        return out

    def _adapt_cfg_to(self, ds):
        """换成真实因子模板，并删掉当前数据不支持的那些因子。"""
        base = os.path.join(os.path.dirname(self.cfg_path), "factors_real.yaml")
        if not os.path.exists(base):
            return self.cfg
        with open(base, "r", encoding="utf-8") as fh:
            cfg = ProjectConfig.from_yaml(fh.read())
        keep = []
        for f in cfg.factors:
            ok = True
            for key, val in (f.inputs or {}).items():
                if not isinstance(val, str):
                    continue
                if val.startswith("field:"):
                    if val.split(":", 1)[1] not in ds.unit_attrs:
                        ok = False
                        break
                elif key in ("network", "layer", "destinations") and val not in ds.layers:
                    ok = False
                    break
            if ok:
                keep.append(f.code)
        cfg.factors = [f for f in cfg.factors if f.code in keep]
        cfg.model["features"] = [c for c in (cfg.model.get("features") or []) if c in keep]
        return cfg

    def import_data(self, spec: Dict) -> Dict:
        name = (spec.get("project_name") or "").strip() or "我的工程"
        ds, notes = build_dataset(spec, project_name=name)

        # 每次都从模板重建配置，保证重复导入不会累积副作用
        from ..config import FactorSpec
        from ..datamodel import UnitTable

        self.cfg = copy.deepcopy(self._cfg_template)

        # 1) 丢掉引用了不存在图层 / 字段的因子
        have_layers = set(ds.layers)
        have_fields = set(ds.unit_attrs) | set(UnitTable.__dataclass_fields__)
        drop = []
        for f in self.cfg.factors:
            for v in f.inputs.values():
                if not isinstance(v, str):
                    continue
                if v.startswith(("factor:", "field:")):
                    if v.startswith("field:") and v.split(":", 1)[1] not in have_fields:
                        drop.append(f.code)
                        break
                elif v not in have_layers:
                    drop.append(f.code)
                    break
        codes_drop = {f.code for f in self.cfg.factors if f.code in drop}
        self.cfg.factors = [f for f in self.cfg.factors if f.code not in codes_drop]
        if codes_drop:
            shown = sorted(codes_drop)
            tail = "等 %d 个" % len(shown) if len(shown) > 6 else ""
            notes.append("已停用 %d 个内置因子（它们引用的图层或字段本次未导入）：%s%s"
                         % (len(shown), "、".join(shown[:6]), tail))

        # 2) 为导入的每个设施图层自动生成可达性因子
        auto = []
        for lid, lyr in ds.layers.items():
            if lyr.layer_type != "point":
                continue
            nm = (lyr.aux_meta or {}).get("display_name") or lid
            for suffix, spec_ in (
                ("_cnt", {"op": "buffer_overlay", "inputs": {"layer": lid},
                          "params": {"radius_m": 1000, "stat": "count"},
                          "outputs": ["value"], "note": "1 公里内%s数量" % nm}),
                ("_dist", {"op": "spatial_join_agg", "inputs": {"layer": lid},
                           "params": {"stat": "nearest_distance"},
                           "outputs": ["value"], "note": "到最近%s的距离" % nm}),
            ):
                code = ("u_%s%s" % (lid, suffix))[:40]
                if any(f.code == code for f in self.cfg.factors):
                    continue
                f = FactorSpec(code=code, op=spec_["op"], inputs=spec_["inputs"],
                               params=spec_["params"], outputs=spec_["outputs"], note=spec_["note"])
                _validate_factor(f)
                self.cfg.factors.append(f)
                auto.append(code)
        if auto:
            notes.append("已自动生成 %d 个可达性因子（每个设施图层：1 公里内数量 + 到最近距离）" % len(auto))

        # 3) 有常住人口时补一个人口密度因子
        if "pop_density" not in ds.unit_attrs and ds.units.population.sum() > 0:
            ds.unit_attrs["pop_density"] = ds.units.population / np.maximum(ds.units.area, 1.0)
            if not any(f.code == "u_pop" for f in self.cfg.factors):
                f = FactorSpec(code="u_pop", op="attribute", inputs={"field": "field:pop_density"},
                               outputs=["value"], note="人口密度")
                _validate_factor(f)
                self.cfg.factors.append(f)
                auto.append("u_pop")

        # 4) 图层注册表跟着导入结果走
        layers = {}
        for lid, lyr in ds.layers.items():
            layers[lid] = {
                "type": lyr.layer_type, "asof_date": lyr.asof_date, "version": lyr.version,
                "name": (lyr.aux_meta or {}).get("display_name", lid),
            }
        self.cfg.layers = layers

        # 5) 建模特征默认用新生成的因子
        self.cfg.model["features"] = [c for c in auto] + [
            c for c in (self.cfg.model.get("features") or []) if c in have_fields and c not in auto
        ]

        self.source = "user"
        self.import_notes = notes
        self._activate(ds)
        return {"notes": notes, "n_units": ds.n_units, "n_obs": ds.n_obs()}

    def reset_demo(self) -> None:
        self.cfg = ProjectConfig.from_yaml(_dump_cfg(self._demo_spec))
        self._cfg_template = copy.deepcopy(self.cfg)
        self.source = "demo"
        self.import_notes = []
        scene = build_demo_dataset()
        self._activate(scene.dataset)

    def preview(self, b64: str, kind: str) -> Dict:
        from ..importer import guess_map, parse_table, read_bytes

        text = read_bytes(b64)
        df = parse_table(text)
        cols = list(df.columns)
        k = "point" if kind == "layer" else kind
        return {
            "columns": cols,
            "rows": int(len(df)),
            "sample": df.head(5).fillna("").astype(str).values.tolist(),
            "guess": guess_map(cols, k),
        }

    # ------------------------------------------------------------------
    # 因子配置
    # ------------------------------------------------------------------
    def update_factors(self, changes: Dict[str, Dict]) -> None:
        for code, ch in (changes or {}).items():
            try:
                f = self.cfg.factor(code)
            except KeyError:
                continue
            if "params" in ch and isinstance(ch["params"], dict):
                f.params = dict(ch["params"])
            if "enabled" in ch:
                f.enabled = bool(ch["enabled"])
            if f.enabled:
                _validate_factor(f)
        self._recompute()

    def add_factor(self, tpl_key: str, name: str, mapping: Dict[str, str],
                   params: Optional[Dict] = None) -> Dict:
        tpl = next((t for t in TEMPLATES if t["key"] == tpl_key), None)
        if not tpl:
            raise ValueError("未知的因子模板")
        idx = 1
        while True:
            code = "u_%s_%d" % (tpl_key, idx)
            if all(f.code != code for f in self.cfg.factors):
                break
            idx += 1
        inputs = {}
        for slot in tpl["inputs"]:
            val = (mapping or {}).get(slot)
            if not val:
                raise ValueError("请为“%s”选择一个输入" % slot)
            inputs[slot] = val
        p = dict(tpl["params"])
        p.update(params or {})
        from ..config import FactorSpec

        spec = FactorSpec(code=code, op=tpl["op"], inputs=inputs, params=p,
                          outputs=[tpl["output_field"]], note=name or tpl["name"])
        _validate_factor(spec)
        self.cfg.factors.append(spec)
        if code not in (self.cfg.model.get("features") or []):
            self.cfg.model["features"] = list(self.cfg.model.get("features") or []) + [code]
        self._recompute()
        return {"code": code, "name": spec.note}

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------
    def export(self, out_dir: str) -> List[str]:
        import pandas as pd

        os.makedirs(out_dir, exist_ok=True)
        res, ds, obs = self.result, self.ds, self.ds.obs
        stats = {x["code"]: x for x in self.factor_stats()}
        arrs = res["arrays"]

        long_df = self.engine.to_long_table(self.run_id)
        val_df = pd.DataFrame({
            "单元编号": ds.units.unit_id,
            "X": np.round(ds.units.x, 2),
            "Y": np.round(ds.units.y, 2),
            "面积_m2": ds.units.area,
            "行政区": ds.units.admin_code,
            "估值单价_中位": arrs["est_median"],
            "估值单价_均值": arrs["est_mean"],
            "P10": arrs["p_low"],
            "P50": arrs["p_mid"],
            "P90": arrs["p_high"],
            "对数残差": arrs["resid"],
        })
        coef_df = pd.DataFrame(res["coef"], columns=["变量", "系数", "标准误", "t", "p", "显著性"])
        vif_df = pd.DataFrame(res["vif"], columns=["变量", "R2_其余", "VIF"])
        m = res["metrics"]
        cv_df = pd.DataFrame([
            ["训练集（样本内）"] + [m["train"][k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
            ["随机 K 折 CV"] + [m["cv_random"][k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
            ["空间分块 CV"] + [m["cv_spatial"][k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
        ], columns=["口径", "R2", "RMSE_log", "MAE_log", "MAPE", "MedAPE"])
        if self.rep:
            run_df = pd.DataFrame(self.rep.as_rows(),
                                  columns=["因子", "算子", "缓存", "耗时(s)", "输出"])
        else:
            # 内置数据包不含运行时报告，这里输出因子清单与算子对应关系，
            # 耗时/缓存留空，避免出现一张只有表头的空表
            run_df = pd.DataFrame(
                [[s["code"], s["op_name"], "内置数据包（无运行记录）", "—",
                  s.get("note") or ""] for s in self.factor_stats()],
                columns=["因子", "算子", "缓存", "耗时(s)", "输出"])
        diag_df = pd.DataFrame([
            ["Moran's I", res["moran"]["i"]], ["E[I]", res["moran"]["e"]],
            ["z", res["moran"]["z"]], ["p", res["moran"]["p"]],
            ["结论", res["moran"]["verdict"]],
        ], columns=["指标", "值"])

        xlsx = write_workbook(os.path.join(out_dir, "估值结果.xlsx"), {
            "估值明细": val_df, "因子长表": long_df, "模型系数": coef_df,
            "共线性": vif_df, "精度对比": cv_df, "空间诊断": diag_df, "因子执行": run_df,
        })

        resid_all = np.array([np.nan if v is None else v for v in arrs["resid"]])
        _bm = getattr(ds, "basemap", {}) or {}
        png = residual_map_png(
            os.path.join(out_dir, "残差专题图.png"),
            resid_all,
            ds.units.x, ds.units.y,
            ds.grid.cell,
            polys=_bm.get("unit_polys"),
            roads=_bm.get("roads"),
            water=_bm.get("water"),
        )

        factor_rows = [[c, stats[c]["op_name"], (stats[c]["note"] or "")[:24],
                        "%.4g" % stats[c]["mean"], "%.4g" % stats[c]["sd"]] for c in res["features"]]
        metric_rows = [
            ["训练集（样本内）"] + [m["train"][k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
            ["随机 K 折 CV"] + [m["cv_random"][k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
            ["空间分块 CV"] + [m["cv_spatial"][k] for k in ("r2", "rmse_log", "mae_log", "mape", "medape")],
        ]
        docx_path = write_calibration_report(os.path.join(out_dir, "校准报告.docx"), {
            "project_name": ds.project_name,
            "crs": ds.crs,
            "n_units": ds.n_units,
            "n_obs": ds.n_obs(),
            "asof_date": ds.units.asof_date,
            "cell_area": ds.grid.area,
            "snap_failed": (self.rep.snap_failures.get("road_net", 0.0)
                            if self.rep else None),
            "snap_mean_dist": (self.rep.snap_mean_dist.get("road_net", 0.0)
                               if self.rep else None),
            "factor_rows": factor_rows,
            "smearing": m["smearing"],
            "coef_rows": res["coef"],
            "vif_threshold": self.cfg.model.get("vif_threshold", 10),
            "vif_rows": [[r[0], "%.2f" % r[1], "%.2f" % r[2]] for r in res["vif"]],
            "metric_rows": metric_rows,
            "ratio": {k: (v if v is not None else float("nan")) for k, v in res["ratio"].items()},
            "moran": _MoranView(res["moran"]),
            "district_rows": [[d["code"], "%.4f" % d["mean"], d["n"], d["tag"]] for d in res["districts"][:12]],
            "run_id": self.run_id,
            "config_fingerprint": self.cfg.fingerprint(),
            "seed": self.cfg.model.get("seed", 0),
            "data_version": self._data_version_text(),
            "data_nature": self._data_nature_text(),
            "engine_version": "1.0.0",
        })
        return [xlsx, docx_path, png]


    def _data_nature_text(self) -> str:
        """导出报告里“数据性质”一栏的文字，按实际成交来源判定。"""
        src = set(str(x) for x in self.ds.obs.source)
        if any('合成' in x for x in src):
            return '合成演示数据，精度指标不代表实盘能力'
        return '小区级真实挂牌价（按 800 米聚合到评估单元），精度指标反映真实价格的可解释程度'

    def _data_version_text(self) -> str:
        """导出报告里“数据版本”一栏的文字。"""
        if self.source == 'user':
            return '用户导入'
        src = set(str(x) for x in self.ds.obs.source)
        return '内置数据包（合成价）' if any('合成' in x for x in src)             else '内置数据包（真实小区挂牌价 2024）'


def _extent_with_basemap(u, bm) -> list:
    """地图视野：本区单元范围 + 1 km 外扩。

    不再把 2.5 km 缓冲内的邻区道路/水体全部包进来，否则静安区地图会
    显示到浦东的细节。底图仍按视野裁剪绘制，区外 1 km 只作地理参照。
    """
    m = 1000.0
    return [float(u.x.min()) - m, float(u.y.min()) - m,
            float(u.x.max()) + m, float(u.y.max()) + m]


def _layer_cn(lid: str, kind: str) -> str:
    table = {
        "road_net": "道路网",
        "poi_cbd": "CBD 中心点",
        "poi_com": "商业网点",
        "poi_metro": "地铁站",
        "poi_school": "中小学校",
        "poi_hospital": "医院",
        "poi_bus": "公交站点",
        "layer_park": "公园绿地",
        "layer_water": "水系",
        "layer_pop": "人口栅格",
        "layer_far": "容积率栅格",
        "layer_built": "建筑密度栅格",
        "layer_noise": "夜间噪声栅格",
    }
    return table.get(lid, lid)


def _dump_cfg(raw: Dict) -> str:
    """把配置字典还原成 YAML 文本（仅用于重置演示数据）。"""
    import json

    # 配置本来就是从 YAML 解析来的 dict；这里用紧凑的自定义序列化避免引入依赖
    lines: List[str] = []

    def emit(node, indent: int) -> None:
        pad = " " * indent
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (dict, list)) and v:
                    lines.append("%s%s:" % (pad, k))
                    emit(v, indent + 2)
                else:
                    lines.append("%s%s: %s" % (pad, k, _scalar(v)))
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    first = True
                    for k, v in item.items():
                        head = "%s- %s" % (pad, k) if first else "%s  %s" % (pad, k)
                        first = False
                        if isinstance(v, (dict, list)) and v:
                            lines.append("%s:" % head)
                            emit(v, indent + 4)
                        else:
                            lines.append("%s: %s" % (head, _scalar(v)))
                else:
                    lines.append("%s- %s" % (pad, _scalar(item)))

    def _scalar(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "[" + ", ".join(_scalar(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{" + ", ".join("%s: %s" % (k, _scalar(x)) for k, x in v.items()) + "}"
        return str(v)

    emit(raw, 0)
    return "\n".join(lines) + "\n"
