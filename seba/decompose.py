# -*- coding: utf-8 -*-
"""价格拆解 + 个性化适配。

和"预测房价"是两件事：
    预测：给定特征 → 猜一个价（要求系数跨区通用，做不到）
    拆解：给定一个已知价格 → 拆成各项特征各贡献了多少（只需局部有效）

方法：
    1. 取目标点周边 radius 米内的成交样本，拟合**局部**特征价格模型
       log(单价) = b0 + Σ b_i · x_i
    2. 用 Shapley 值把「目标价 − 基准价」精确分摊到每个因子
       （乘法模型下 Shapley 可加且公平：Σ 各项 = 总溢价）
    3. Bootstrap 重抽样，给出每项贡献的置信区间
    4. 按用户的支付意愿权重重新加总，得到「适配价」和「冤枉钱」

用法：
    python decompose.py --unit V00247
    python decompose.py --unit V00247 --price 118640 --radius 1200
    python decompose.py --unit V00247 --pref rt_metro_time=0
"""
from __future__ import annotations

import argparse
import itertools
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Tuple



# 因子的中文名与"对买家意味着什么"
BUYER_HINT = {
    "rt_metro_time": "通勤（不坐地铁的人可设 0）",
    "rt_shop_1km": "日常购物便利",
    "rt_green_500": "绿化环境",
    "rt_built_share": "建成密度",
    "rt_road_density": "路网密度",
    "rt_isect_dens": "路口密度（通达性）",
    "cp_gravity": "区位等级（综合）",
    "rt_comm_share": "商业配套用地",
    "sch_dist": "学校距离",
}


@dataclass
class Item:
    code: str
    name: str
    contribution: float          # 金额（元/㎡），可正可负
    lo: float = 0.0              # Bootstrap 5%
    hi: float = 0.0              # Bootstrap 95%
    log_contrib: float = 0.0


@dataclass
class Decomposition:
    unit_id: str
    asking_price: float          # 待拆解的价格（元/㎡）
    base_price: float            # 局部子市场的基准价
    model_price: float           # 模型认为的合理价
    unexplained: float           # 挂牌价 − 模型价（模型解释不了的个体差异）
    items: List[Item] = field(default_factory=list)
    n_samples: int = 0
    radius: float = 0.0
    r2: float = 0.0
    coeffs: Dict[str, float] = field(default_factory=dict)
    bad_sign: List[str] = field(default_factory=list)


def _fit_local(X, y, feats, lam=3.0):
    """带 L2 正则的 OLS（局部样本少，必须正则化）。"""
    import numpy as np

    X1 = np.column_stack([np.ones(len(y)), X])
    n, p = X1.shape
    reg = lam * np.eye(p)
    reg[0, 0] = 0.0
    beta = np.linalg.solve(X1.T @ X1 + reg, X1.T @ y)
    pred = X1 @ beta
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1e-12
    return beta, 1.0 - ss_res / ss_tot


def _shapley(ratios, base):
    """乘法模型的 Shapley 分解：把 base*(Πr_i - 1) 分摊到各因子。

    ratios: 每个因子的 (r_i - 1)，r_i = exp(b_i·(x_i - x̄_i))
    返回与 ratios 等长的贡献列表，满足 Σ = base*(Πr - 1)
    """
    n = len(ratios)
    r = [1.0 + d for d in ratios]
    phi = [0.0] * n
    idx = list(range(n))
    # 精确 Shapley：枚举全部子集（n≤10 时 2^n 可接受）
    from math import factorial

    for i in idx:
        others = [j for j in idx if j != i]
        acc = 0.0
        for k in range(len(others) + 1):
            w = factorial(k) * factorial(n - k - 1) / factorial(n)
            for S in itertools.combinations(others, k):
                prod = 1.0
                for j in S:
                    prod *= r[j]
                acc += w * prod
        phi[i] = base * (r[i] - 1.0) * acc
    return phi


def decompose(ds, weights: Dict[str, float], target_idx: int,
              asking_price: float = None, radius: float = 1500.0,
              min_n: int = 60, n_boot: int = 200, seed: int = 20261118) -> Decomposition:
    import numpy as np

    obs = ds.obs
    ui = np.asarray(obs.unit_idx)
    y_all = np.asarray(obs.unit_price, dtype=float)
    ux, uy = ds.units.x, ds.units.y
    tx, ty = float(ux[target_idx]), float(uy[target_idx])

    # 1) 选局部样本，样本不足就逐步扩大半径
    r = radius
    sel = np.array([], dtype=int)
    for _ in range(6):
        d = np.hypot(ux[ui] - tx, uy[ui] - ty)
        sel = np.where((d <= r) & (ui != target_idx))[0]
        if len(sel) >= min_n:
            break
        r *= 1.6
    if len(sel) < 15:
        raise RuntimeError("周边 %.0f 米内只有 %d 条成交，样本太少无法拆解"
                           % (r, len(sel)))

    # 只用有变化的因子（96% 取值相同的因子是伪变量，放进去会污染拆解）
    import numpy as _np
    feats = []
    for c in weights:
        if c not in ds.attrs:
            continue
        v = ds.attrs[c]
        lo2, hi2 = _np.percentile(v, 2), _np.percentile(v, 98)
        if _np.isfinite(lo2) and _np.isfinite(hi2) and abs(hi2 - lo2) > 1e-12:
            feats.append(c)
    if not feats:
        raise RuntimeError("没有可用因子")
    Xall = ds.design_matrix(feats)
    X = Xall[ui][sel]
    y = np.log(y_all[sel])

    # 2) 拟合局部模型
    beta, r2 = _fit_local(X, y, feats)
    b0, coef = beta[0], beta[1:]
    xbar = X.mean(axis=0)
    xt = Xall[target_idx]

    # 基准价：把目标点的特征换成局部样本均值时的预测价
    log_base = float(b0 + xbar @ coef)
    base = math.exp(log_base)

    # 3) 各因子相对均值的对数偏离
    dev = (xt - xbar)
    log_terms = coef * dev
    ratios = [math.exp(v) - 1.0 for v in log_terms]
    phi = _shapley(ratios, base)

    # 模型合理价
    log_model = log_base + float(log_terms.sum())
    model_price = math.exp(log_model)

    price = float(asking_price) if asking_price else float(
        ds.obs.unit_price[np.where(ui == target_idx)[0][0]]) if (ui == target_idx).any() \
        else model_price

    # 4) Bootstrap 区间
    boots = np.zeros((n_boot, len(feats)))
    rng = np.random.default_rng(seed)
    for b in range(n_boot):
        pick = rng.integers(0, len(sel), len(sel))
        Xb, yb = X[pick], y[pick]
        try:
            bb, _ = _fit_local(Xb, yb, feats)
        except Exception:
            boots[b] = phi
            continue
        cb = bb[1:]
        lb = float(bb[0] + Xb.mean(axis=0) @ cb)
        baseb = math.exp(lb)
        tb = cb * (xt - Xb.mean(axis=0))
        rb = [math.exp(v) - 1.0 for v in tb]
        boots[b] = _shapley(rb, baseb)
    lo = np.percentile(boots, 5, axis=0)
    hi = np.percentile(boots, 95, axis=0)

    from seba.labels import factor_name

    # 期望符号（用于发现局部样本导致的异常系数）
    EXPECT = {'rt_metro_time': -1, 'rt_shop_1km': +1, 'rt_green_500': +1,
              'rt_built_share': +1, 'rt_road_density': +1, 'rt_isect_dens': +1,
              'cp_gravity': +1, 'rt_comm_share': +1, 'sch_dist': -1}
    bad_sign = [c for i, (c, v) in enumerate(zip(feats, coef))
                if EXPECT.get(c, 0) and (v * EXPECT[c] < 0)
                and not (lo[i] <= 0 <= hi[i])]

    items = []
    for i, c in enumerate(feats):
        try:
            nm = factor_name(c, "")
        except Exception:
            nm = c
        items.append(Item(code=c, name=nm, contribution=float(phi[i]),
                          lo=float(lo[i]), hi=float(hi[i]),
                          log_contrib=float(log_terms[i])))
    items.sort(key=lambda it: -abs(it.contribution))

    return Decomposition(
        unit_id=str(ds.units.unit_id[target_idx]),
        asking_price=price,
        base_price=base,
        model_price=model_price,
        unexplained=price - model_price,
        items=items,
        n_samples=int(len(sel)),
        radius=float(r),
        r2=float(r2),
        coeffs={c: float(v) for c, v in zip(feats, coef)},
        bad_sign=bad_sign,
    )


def personalize(dec: Decomposition, weights: Dict[str, float]) -> Tuple[float, List[Item]]:
    """按用户支付意愿重新加总：适配价 = 基准 + Σ w_i · 贡献_i。"""
    adapted = dec.base_price
    wasted = []
    for it in dec.items:
        w = float(weights.get(it.code, 1.0))
        adapted += w * it.contribution
        if w < 1.0 and it.contribution > 0:
            cut = (1.0 - w) * it.contribution
            wasted.append(Item(code=it.code, name=it.name, contribution=cut,
                               lo=(1 - w) * it.lo, hi=(1 - w) * it.hi))
    wasted.sort(key=lambda x: -x.contribution)
    return adapted, wasted


def _money(v: float) -> str:
    return ("{:,.0f}".format(round(v)))


def render(dec: Decomposition, weights: Dict[str, float], adapted: float,
           wasted: List[Item], area: float = 90.0) -> str:
    L = []
    L.append("=" * 74)
    L.append("  价格拆解  ·  单元 %s" % dec.unit_id)
    L.append("=" * 74)
    L.append("  待拆解价格        %s 元/㎡" % _money(dec.asking_price))
    L.append("  局部子市场基准价  %s 元/㎡   （周边 %.0f 米内 %d 套成交，R²=%.2f）"
             % (_money(dec.base_price), dec.radius, dec.n_samples, dec.r2))
    L.append("  各因素加总        %s 元/㎡" % _money(dec.model_price))
    L.append("  模型未解释部分    %+s 元/㎡  （楼层/朝向/装修/业主心态）"
             % _money(dec.unexplained))
    L.append("")
    L.append("-" * 74)
    L.append("  %-26s %12s %22s" % ("因素", "贡献(元/㎡)", "90% 置信区间"))
    L.append("-" * 74)
    tiny = 0.0
    tiny_n = 0
    for it in dec.items:
        if abs(it.contribution) < 1:
            tiny += it.contribution
            tiny_n += 1
            continue
        sig = "" if (it.lo <= 0 <= it.hi) else " *"
        L.append("  %-24s %+12s   [%s, %s]%s"
                 % (it.name[:24], _money(it.contribution),
                    _money(it.lo), _money(it.hi), sig))
    if tiny_n:
        L.append("  %-24s %+12s   （%d 个因素影响均 < 1 元）"
                 % ("其他", _money(tiny), tiny_n))
    L.append("-" * 74)
    L.append("  合计溢价          %+s 元/㎡"
             % _money(dec.model_price - dec.base_price))
    L.append("  （标 * 的表示 90% 区间跨过 0，方向不确定）")
    L.append("")
    # ---- 质量评级 ----
    issues = []
    if dec.n_samples < 100:
        issues.append("样本仅 %d 套成交，系数估计不稳" % dec.n_samples)
    if dec.r2 < 0.5:
        issues.append("局部模型 R² 仅 %.2f，解释力偏弱" % dec.r2)
    if dec.bad_sign:
        nm = "、".join(dec.bad_sign[:3])
        issues.append("以下因子局部系数方向与常识相反（样本少导致）：%s" % nm)
    if abs(dec.unexplained) / max(dec.asking_price, 1) > 0.15:
        issues.append("有 %.0f%% 的价格无法被因素解释（多为楼层/朝向/装修）"
                      % (abs(dec.unexplained) / dec.asking_price * 100))
    level = "高" if not issues else ("中" if len(issues) == 1 else "低")
    L.append("  【拆解可信度】%s" % level)
    for x in issues:
        L.append("    · " + x)
    if not issues:
        L.append("    · 样本量充足、解释力可接受、系数方向正常")
    L.append("")
    if wasted or any(w < 1 for w in weights.values()):
        L.append("=" * 74)
        L.append("  按你的偏好重新计算")
        L.append("=" * 74)
        off = [c for c, w in weights.items() if w < 1]
        if off:
            L.append("  你不付费的因素：%s" % "、".join(
                BUYER_HINT.get(c, c) for c in off))
        L.append("")
        L.append("  市场价            %s 元/㎡" % _money(dec.model_price))
        L.append("  对你而言的适配价  %s 元/㎡" % _money(adapted))
        diff = dec.model_price - adapted
        if diff > 0:
            L.append("  ▲ 你为不需要的东西多付 %s 元/㎡" % _money(diff))
        else:
            L.append("  ▼ 你占到了 %s 元/㎡ 的便宜" % _money(-diff))
        L.append("")
        L.append("  按 90 ㎡ 折算：")
        L.append("    市场总价        %s 元" % _money(dec.model_price * area))
        L.append("    你的适配总价    %s 元" % _money(adapted * area))
        L.append("    差额            %s 元" % _money(diff * area))
        if wasted:
            L.append("")
            L.append("  冤枉钱明细：")
            for it in wasted[:6]:
                L.append("    %-24s %s 元/㎡  （合计 %s 元）"
                         % (it.name[:24], _money(it.contribution),
                            _money(it.contribution * area)))
    L.append("=" * 74)
    return "\n".join(L)
