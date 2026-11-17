# -*- coding: utf-8 -*-
"""空间误差诊断：残差的全局空间自相关检验、失配板块清单、残差专题图。

局部统计量（Getis-Ord Gi*、LISA）按《实现方案》第八章的功能边界划归件 3，
本件只做全局检验与聚合诊断。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

__all__ = ["MoranResult", "morans_i", "residual_map_png", "district_summary"]


@dataclass
class MoranResult:
    i: float
    e_i: float
    sd: float
    z: float
    p: float
    n_perm: int

    def verdict(self) -> str:
        if not np.isfinite(self.p):
            return "无法判定"
        if self.p < 0.05 and self.i > self.e_i:
            return "残差存在显著正空间自相关：全局模型假设不成立，建议转局部模型（件 3）"
        if self.p < 0.05 and self.i < self.e_i:
            return "残差存在显著负空间自相关：模型在相邻单元间反复锯齿，检查因子口径"
        return "残差无显著空间自相关：全局模型的空间假设可接受"


def _knn_neighbors(x: np.ndarray, y: np.ndarray, k: int = 6) -> List[List[int]]:
    """k 近邻邻接。规则格网与不规则点位都适用。"""
    n = x.size
    k = max(1, min(int(k), n - 1))
    nb: List[List[int]] = [[] for _ in range(n)]
    chunk = 512
    for s in range(0, n, chunk):
        e = min(s + chunk, n)
        dx = x[s:e, None] - x[None, :]
        dy = y[s:e, None] - y[None, :]
        d2 = dx * dx + dy * dy
        for i in range(e - s):
            d2[i, s + i] = np.inf
        idx = np.argpartition(d2, k - 1, axis=1)[:, :k]
        for i in range(e - s):
            nb[s + i] = [int(j) for j in idx[i] if j != s + i]
    return nb


def morans_i(
    values: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    k: int = 6,
    n_perm: int = 499,
    seed: int = 0,
) -> MoranResult:
    """行标准化的全局 Moran's I + 置换检验（k 近邻空间权重）。"""
    z = np.asarray(values, dtype=float)
    zc = z - z.mean()
    s2 = float((zc ** 2).sum())
    n = z.size
    if s2 <= 0 or n < 5:
        return MoranResult(float("nan"), float("nan"), float("nan"), float("nan"), float("nan"), n_perm)

    nb = _knn_neighbors(np.asarray(x, dtype=float), np.asarray(y, dtype=float), k)
    deg = np.array([len(v) for v in nb], dtype=float)
    deg = np.where(deg > 0, deg, 1.0)

    def _I(vec: np.ndarray) -> float:
        lag = np.zeros(n)
        for i in range(n):
            if nb[i]:
                lag[i] = vec[nb[i]].sum() / deg[i]
        return float((vec * lag).sum() / s2)

    obs = _I(zc)
    rng = np.random.default_rng(seed)
    sims = np.empty(n_perm)
    for b in range(n_perm):
        perm = rng.permutation(zc)
        sims[b] = _I(perm)

    e_i = -1.0 / (n - 1)
    sd = float(np.std(sims, ddof=1))
    zscore = (obs - e_i) / sd if sd > 0 else float("nan")
    # 单侧（正相关）检验：与"更极端"的置换次数比较，加一避免 p=0
    p = (1.0 + float((sims >= obs).sum())) / (1.0 + n_perm)
    return MoranResult(i=obs, e_i=e_i, sd=sd, z=zscore, p=p, n_perm=n_perm)


def district_summary(
    admin_code: np.ndarray,
    resid: np.ndarray,
    threshold: float = 1.5,
) -> List[Tuple[str, float, int, str]]:
    """按行政单元聚合残差均值，输出系统性高估 / 低估板块清单。"""
    rows: List[Tuple[str, float, int, str]] = []
    for code in sorted(set(admin_code.tolist())):
        m = admin_code == code
        if m.sum() == 0:
            continue
        mu = float(resid[m].mean())
        sd = float(resid[m].std(ddof=1)) if m.sum() > 2 else float("nan")
        se = sd / np.sqrt(m.sum()) if np.isfinite(sd) and m.sum() > 1 else float("nan")
        t = mu / se if (np.isfinite(se) and se > 0) else float("nan")
        if np.isfinite(t) and abs(t) >= threshold:
            tag = "系统性低估" if mu > 0 else "系统性高估"
        else:
            tag = "无明显偏离"
        rows.append((str(code), mu, int(m.sum()), tag))
    rows.sort(key=lambda r: -abs(r[1]))
    return rows


def _diverging_color(v: float, vmax: float) -> Tuple[int, int, int]:
    """蓝—白—红双向色带：负残差（高估）蓝，正残差（低估）红。"""
    if vmax <= 0:
        return (245, 245, 245)
    t = max(-1.0, min(1.0, v / vmax))
    if t >= 0:
        a = t
        return (
            int(247 + (196 - 247) * a),
            int(247 + (58 - 247) * a),
            int(247 + (58 - 247) * a),
        )
    a = -t
    return (
        int(247 + (43 - 247) * a),
        int(247 + (108 - 247) * a),
        int(247 + (196 - 247) * a),
    )


def _load_cjk_font(size: int):
    """找一个带中文字形的系统字体；找不到就退回默认字体并用英文标注。"""
    import os

    from PIL import ImageFont

    win = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "Deng.ttf", "simsun.ttc"):
        p = os.path.join(win, "Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return None


def residual_map_png(
    path: str,
    resid: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    cell: float,
    pad: int = 28,
) -> str:
    """按单元坐标画残差专题图（无 matplotlib 依赖）。"""
    from PIL import Image, ImageDraw

    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    cell = float(cell) if cell else 250.0
    x0, y0 = float(xs.min()), float(ys.min())
    nx = max(1, int((xs.max() - x0) / cell) + 1)
    ny = max(1, int((ys.max() - y0) / cell) + 1)
    # 输出尺寸上限：全市 900 多格时按 1 像素画，区级按 6–18 像素画
    scale = int(max(1, min(18, 1200 / max(nx, ny))))

    img = Image.new("RGB", (nx * scale + pad * 2, ny * scale + pad * 2 + 52), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    font = _load_cjk_font(11)

    vmax = float(np.percentile(np.abs(resid), 95)) if resid.size else 1.0
    vmax = vmax if vmax > 0 else 1.0

    for k in range(resid.size):
        cx = int((xs[k] - x0) / cell)
        cy = int((ys[k] - y0) / cell)
        x1 = pad + cx * scale
        y1 = pad + (ny - 1 - cy) * scale
        dr.rectangle([x1, y1, x1 + scale - 1, y1 + scale - 1],
                     fill=_diverging_color(float(resid[k]), vmax))

    dr.rectangle([pad, pad, pad + nx * scale - 1, pad + ny * scale - 1], outline=(90, 90, 90))

    ly = pad + ny * scale + 16
    bar_w = 220
    for i in range(bar_w):
        v = (i / (bar_w - 1) * 2 - 1) * vmax
        dr.line([(pad + i, ly), (pad + i, ly + 10)], fill=_diverging_color(v, vmax))
    if font is None:
        dr.text((pad, ly - 14), "Residual (blue=over, red=under), +/-%.3f" % vmax, fill=(40, 40, 40))
        dr.text((pad, ly + 13), "- over", fill=(60, 60, 60))
        dr.text((pad + bar_w - 34, ly + 13), "under +", fill=(60, 60, 60))
    else:
        dr.text((pad, ly - 15), "残差专题图：蓝=高估，红=低估（±%.3f）；空白=无成交样本" % vmax,
                fill=(40, 40, 40), font=font)
        dr.text((pad, ly + 13), "− 高估", fill=(60, 60, 60), font=font)
        dr.text((pad + bar_w - 36, ly + 13), "低估 +", fill=(60, 60, 60), font=font)

    img.save(path)
    return path
