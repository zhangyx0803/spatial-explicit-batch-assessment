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
    """蓝-白-红双向色带：负残差（高估）蓝，正残差（低估）红。"""
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
    polys=None,
    roads=None,
    water=None,
    max_px: int = 1500,
) -> str:
    """残差专题图：有面数据则填色（含路网/水体底图），否则退回方块网格。"""
    from PIL import Image, ImageDraw

    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    resid = np.asarray(resid, dtype=float)

    # 覆盖范围：优先用面数据，边界更贴合
    if polys:
        px = [v for f in polys if f for i, v in enumerate(f) if i % 2 == 0]
        py = [v for f in polys if f for i, v in enumerate(f) if i % 2 == 1]
        x0, x1 = (min(px), max(px)) if px else (float(xs.min()), float(xs.max()))
        y0, y1 = (min(py), max(py)) if py else (float(ys.min()), float(ys.max()))
    else:
        c = float(cell) if cell else 250.0
        x0, x1 = float(xs.min()), float(xs.max()) + c
        y0, y1 = float(ys.min()), float(ys.max()) + c
    w = max(1e-6, x1 - x0)
    h = max(1e-6, y1 - y0)
    sc = min((max_px - pad * 2) / w, (max_px * 0.86 - pad * 2) / h)
    W = int(w * sc + pad * 2)
    H = int(h * sc + pad * 2 + 58)

    X = lambda x: pad + (x - x0) * sc
    Y = lambda y: pad + (y1 - y) * sc

    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    font = _load_cjk_font(12)
    small = _load_cjk_font(10)

    # 底图：水体
    if water:
        for f in water:
            if not f or len(f) < 6:
                continue
            pts = [(X(f[i]), Y(f[i + 1])) for i in range(0, len(f), 2)]
            dr.polygon(pts, fill=(222, 234, 246))

    vmax = float(np.percentile(np.abs(resid[np.isfinite(resid)]), 95)) if np.isfinite(resid).any() else 1.0
    vmax = vmax if vmax > 0 else 1.0

    # 单元面填色
    used_poly = False
    if polys and len(polys) == resid.size:
        for k, f in enumerate(polys):
            if not f or len(f) < 6:
                continue
            used_poly = True
            pts = [(X(f[i]), Y(f[i + 1])) for i in range(0, len(f), 2)]
            v = resid[k]
            if not np.isfinite(v):
                fill, out = (242, 244, 246), (226, 229, 233)
            else:
                fill, out = _diverging_color(float(v), vmax), (255, 255, 255)
            dr.polygon(pts, fill=fill, outline=out)

    # 底图：路网（压在面色之上、用浅色细线，保证可读）
    if roads:
        for seg in roads:
            if not seg or len(seg) < 4:
                continue
            pts = [(X(seg[i]), Y(seg[i + 1])) for i in range(0, len(seg), 2)]
            dr.line(pts, fill=(196, 201, 207), width=1)

    # 无面数据时退回方块
    if not used_poly:
        c = float(cell) if cell else 250.0
        s2 = max(2, int(c * sc))
        for k in range(resid.size):
            if not np.isfinite(resid[k]):
                continue
            cx = int((xs[k] - x0) / c)
            cy = int((ys[k] - y0) / c)
            xa = int(X(x0 + cx * c))
            ya = int(Y(y0 + (cy + 1) * c))
            dr.rectangle([xa, ya, xa + s2 - 1, ya + s2 - 1],
                         fill=_diverging_color(float(resid[k]), vmax))

    # 图例
    ly = pad + int(h * sc) + 18
    bar_w = 240
    for i in range(bar_w):
        v = (i / (bar_w - 1) * 2 - 1) * vmax
        dr.line([(pad + i, ly), (pad + i, ly + 9)], fill=_diverging_color(v, vmax))
    cap = "残差专题图：蓝＝高估，红＝低估（±%.3f）；灰白＝无成交样本" % vmax
    if font is None:
        dr.text((pad, ly - 15), cap.encode("ascii", "ignore").decode() or "Residual map",
                fill=(40, 40, 40))
        dr.text((pad, ly + 12), "- over", fill=(60, 60, 60))
        dr.text((pad + bar_w - 34, ly + 12), "under +", fill=(60, 60, 60))
    else:
        dr.text((pad, ly - 16), cap, fill=(40, 40, 40), font=font)
        dr.text((pad, ly + 12), "− 高估", fill=(60, 60, 60), font=small)
        dr.text((pad + bar_w - 36, ly + 12), "低估 +", fill=(60, 60, 60), font=small)

    img.save(path)
    return path
