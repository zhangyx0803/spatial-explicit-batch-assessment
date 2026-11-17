# -*- coding: utf-8 -*-
"""比率研究（Ratio Study）：按 IAAO 口径实现 COD 与 PRD。

口径要点（容易做错，这里写死）：
  COD = 100 × [ Σ|R_i − M| / n ] / M
        分子是各比率与**中位数比率**的绝对偏差的**算术平均**，
        不是"中位绝对偏差"，也不做 0.6745 换算。
        用错口径会把 COD 系统性放大约 25%，恰好越过合格线。
  PRD = 算术平均比率 / 按价格加权的平均比率
"""

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
