# -*- coding: utf-8 -*-
"""因子计算引擎：解析 -> 建 DAG -> 拓扑排序 -> 执行 -> 缓存 -> 落 attr 表。

缓存键 = (算子名, 算子版本, 参数指纹, 各输入的版本指纹)。
算子代码或任一层图层版本变化都会让缓存失效，同参数不重算。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from .config import FactorSpec, ProjectConfig
from .datamodel import Dataset
from .operators import OP_FUNCS, RuntimeContext

__all__ = ["FactorEngine", "EngineReport", "OP_VERSION"]

OP_VERSION = "1.0.0"   # 算子实现版本：改了算法必须改这个号，否则会命中旧缓存

@dataclass
class FactorRun:
    code: str
    op: str
    cache_hit: bool
    seconds: float
    outputs: List[str] = field(default_factory=list)
    note: str = ""

@dataclass
class EngineReport:
    runs: List[FactorRun] = field(default_factory=list)
    dependency_edges: List[tuple] = field(default_factory=list)
    snap_failures: Dict[str, float] = field(default_factory=dict)
    snap_mean_dist: Dict[str, float] = field(default_factory=dict)

    @property
    def n_cache_hit(self) -> int:
        return sum(1 for r in self.runs if r.cache_hit)

    @property
    def total_seconds(self) -> float:
        return sum(r.seconds for r in self.runs)

    def as_rows(self) -> List[List[str]]:
        return [
            [r.code, r.op, "命中" if r.cache_hit else "计算", "%.3f" % r.seconds, ", ".join(r.outputs)]
            for r in self.runs
        ]

class FactorEngine:
    def __init__(self, cfg: ProjectConfig, ds: Dataset, ctx: Optional[RuntimeContext] = None):
        self.cfg = cfg
        self.ds = ds
        self.ctx = ctx or RuntimeContext(ds)
        self._cache: Dict[str, Dict[str, np.ndarray]] = {}
        self._factor_sig: Dict[str, str] = {}

    # 缓存键
    def cache_key(self, f: FactorSpec) -> str:
        parts = [f.op, OP_VERSION, f.signature()]
        for val in f.inputs.values():
            if not isinstance(val, str):
                parts.append(str(val))
                continue
            if val.startswith("factor:"):
                code = val.split(":", 1)[1]
                parts.append("F:%s:%s" % (code, self.cfg.factor(code).signature()))
            elif val.startswith("field:"):
                parts.append("A:%s" % val)
            else:
                ver = (self.cfg.layers.get(val) or {}).get("version", "?")
                parts.append("L:%s:%s" % (val, ver))
        blob = "|".join(parts)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    # 执行
    def run(self, progress: Optional[Callable[[str, bool, float], None]] = None) -> EngineReport:
        rep = EngineReport()
        order = self.cfg.topological_order()

        deps = self.cfg.dependencies()
        for code, ds_ in deps.items():
            for d in ds_:
                rep.dependency_edges.append((d, code))

        for code in order:
            f = self.cfg.factor(code)
            key = self.cache_key(f)
            t0 = time.perf_counter()

            if key in self._cache:
                res = self._cache[key]
                hit = True
                elapsed = time.perf_counter() - t0
            else:
                func = OP_FUNCS.get(f.op)
                if func is None:
                    raise KeyError("算子未实现：%s" % f.op)
                res = func(self.ctx, self.ds, f)
                self._cache[key] = res
                hit = False
                elapsed = time.perf_counter() - t0

            primary_name = f.outputs[0] if f.outputs else next(iter(res))
            if primary_name not in res:
                raise KeyError(
                    "因子 %s 声明的输出 %r 不在算子结果中（可用：%s）"
                    % (code, primary_name, ", ".join(res))
                )
            arr = np.asarray(res[primary_name], dtype=float)
            if arr.shape != (self.ds.n_units,):
                raise ValueError(
                    "因子 %s 的结果长度 %s 与单元数 %d 不一致" % (code, arr.shape, self.ds.n_units)
                )
            # 不允许静默产生 NaN：出现即报错，交由质量报告记录
            n_nan = int(np.isnan(arr).sum())
            if n_nan:
                raise ValueError("因子 %s 产生 %d 个 NaN，请检查输入数据" % (code, n_nan))

            self.ds.attrs[code] = arr
            self._factor_sig[code] = f.signature()
            rep.runs.append(
                FactorRun(
                    code=code,
                    op=f.op,
                    cache_hit=hit,
                    seconds=elapsed,
                    outputs=[primary_name],
                    note=f.note,
                )
            )
            if progress:
                progress(code, hit, elapsed)

        rep.snap_failures = dict(self.ctx.snap_failures)
        rep.snap_mean_dist = dict(self.ctx.snap_mean_dist)
        return rep

    # attr 长表导出
    def to_long_table(self, run_id: str):
        import pandas as pd

        rows = []
        for code, arr in self.ds.attrs.items():
            f = self.cfg.factor(code)
            # 该因子主要输入对应的图层版本，便于追溯用的是哪一版图
            layer_ver = "-"
            for _k, _v in (f.inputs or {}).items():
                _lay = self.ds.layers.get(str(_v))
                if _lay is not None and getattr(_lay, "version", None):
                    layer_ver = str(_lay.version)
                    break
            rows.append(
                pd.DataFrame(
                    {
                        "unit_id": self.ds.units.unit_id,
                        "factor_code": code,
                        "value": arr,
                        "source": f.op,
                        "layer_version": layer_ver,
                        "run_id": run_id,
                        "asof_date": self.ds.units.asof_date,
                    }
                )
            )
        return pd.concat(rows, ignore_index=True)
