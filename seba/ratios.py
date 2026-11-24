# -*- coding: utf-8 -*-
"""比率研究：按 IAAO 口径计算离散系数 COD 与价格相关差 PRD。"""

from __future__ import annotations

from typing import Dict

import numpy as np

__all__ = ["ratio_study"]

def ratio_study(
    estimated: np.ndarray,
    sale: np.ndarray,
    cod_max: float = 15.0,
    prd_range=(0.98, 1.03),
) -> Dict[str, float]:
    est = np.asarray(estimated, dtype=float)
    sale = np.asarray(sale, dtype=float)
    ok = np.isfinite(est) & np.isfinite(sale) & (sale > 0)
    est, sale = est[ok], sale[ok]
    if est.size == 0:
        return {"n": 0.0}

    r = est / sale
    med = float(np.median(r))
    mean_r = float(r.mean())
    mad_mean = float(np.mean(np.abs(r - med)))          # 平均绝对偏差（IAAO 分子）
    cod = 100.0 * mad_mean / med if med > 0 else float("nan")
    prd = mean_r / float((r * sale).sum() / sale.sum()) if sale.sum() > 0 else float("nan")

    return {
        "n": float(est.size),
        "median_ratio": med,
        "mean_ratio": mean_r,
        "cod": cod,
        "prd": prd,
        "cod_ok": float(cod <= cod_max) if np.isfinite(cod) else 0.0,
        "prd_ok": float(prd_range[0] <= prd <= prd_range[1]) if np.isfinite(prd) else 0.0,
        "cod_max": float(cod_max),
        "prd_low": float(prd_range[0]),
        "prd_high": float(prd_range[1]),
    }
