# -*- coding: utf-8 -*-
"""模型层：对数变换、Duan smearing、共线性、模型族、空间分块交叉验证。

不依赖 statsmodels / scikit-learn，全部用 numpy 实现，便于做成零依赖的可运行版。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

__all__ = [
    "TStat",
    "t_pvalue",
    "vif_table",
    "ols_fit",
    "ridge_fit",
    "duan_smearing",
    "random_cv",
    "spatial_block_cv",
    "ModelResult",
    "fit_and_evaluate",
]


# --------------------------------------------------------------------------
# 1. Student t 分布（统计量 p 值用，避免硬依赖 scipy）
# --------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 200, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_pvalue(t: float, df: float) -> float:
    """双侧 p 值。"""
    if not np.isfinite(t) or df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return float(_betai(df / 2.0, 0.5, x))


@dataclass
class TStat:
    coef: float
    se: float
    t: float
    p: float


# --------------------------------------------------------------------------
# 2. 线性模型
# --------------------------------------------------------------------------

@dataclass
class ModelResult:
    names: List[str]
    coef: np.ndarray
    se: np.ndarray
    t: np.ndarray
    p: np.ndarray
    r2: float
    adj_r2: float
    rmse_log: float
    dof: int
    smearing: float
    family: str
    lam: float = 0.0

    def rows(self) -> List[List[str]]:
        out = []
        for k, name in enumerate(self.names):
            stars = "***" if self.p[k] < 0.001 else ("**" if self.p[k] < 0.01 else ("*" if self.p[k] < 0.05 else ""))
            out.append(
                [
                    name,
                    "%.5f" % self.coef[k],
                    "%.5f" % self.se[k],
                    "%.2f" % self.t[k],
                    "%.4f" % self.p[k],
                    stars,
                ]
            )
        return out


def _design(X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(X.shape[0]), X])


def ols_fit(X: np.ndarray, y: np.ndarray, names: Sequence[str]) -> ModelResult:
    Xd = _design(X)
    n, p = Xd.shape
    xtx = Xd.T @ Xd
    xtx_inv = np.linalg.pinv(xtx)
    beta = xtx_inv @ Xd.T @ y
    resid = y - Xd @ beta
    rss = float(resid @ resid)
    dof = max(n - p, 1)
    sigma2 = rss / dof
    cov = sigma2 * xtx_inv
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    t = beta / np.where(se > 0, se, np.nan)
    pv = np.array([t_pvalue(float(ti), dof) for ti in t])
    ybar = float(y.mean())
    tss = float(((y - ybar) ** 2).sum())
    r2 = 1.0 - rss / tss if tss > 0 else 0.0
    adj = 1.0 - (1.0 - r2) * (n - 1) / dof if dof > 0 else r2
    rmse_log = math.sqrt(sigma2)
    sm = duan_smearing(resid)
    return ModelResult(
        names=["常数项"] + list(names),
        coef=beta, se=se, t=t, p=pv,
        r2=r2, adj_r2=adj, rmse_log=rmse_log, dof=dof,
        smearing=sm, family="OLS",
    )


def ridge_fit(X: np.ndarray, y: np.ndarray, names: Sequence[str], lam: float = 1.0) -> ModelResult:
    """岭回归：标准化后求解，系数换算回原始量纲后再报告。"""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    Xs = (X - mu) / sd
    ybar = float(y.mean())
    ys = y - ybar
    n, p = Xs.shape
    A = Xs.T @ Xs + lam * np.eye(p)
    beta_s = np.linalg.solve(A, Xs.T @ ys)
    beta = beta_s / sd
    b0 = ybar - float(mu @ beta)
    resid = y - (b0 + X @ beta)
    rss = float(resid @ resid)
    tss = float(((y - ybar) ** 2).sum())
    r2 = 1.0 - rss / tss if tss > 0 else 0.0
    dof = max(n - p, 1)
    # 岭回归不给出可信的标准误与 p 值：这里返回 NaN，报告里如实标注
    nan = np.full(p + 1, np.nan)
    return ModelResult(
        names=["常数项"] + list(names),
        coef=np.concatenate([[b0], beta]),
        se=nan, t=nan, p=nan,
        r2=r2, adj_r2=float("nan"), rmse_log=math.sqrt(rss / dof), dof=dof,
        smearing=duan_smearing(resid), family="Ridge", lam=lam,
    )


# --------------------------------------------------------------------------
# 3. 共线性
# --------------------------------------------------------------------------

def vif_table(X: np.ndarray, names: Sequence[str]) -> List[List]:
    """方差膨胀因子：以第 j 列对其余列回归的 R² 计算。"""
    rows = []
    p = X.shape[1]
    for j in range(p):
        others = np.delete(X, j, axis=1)
        Xd = _design(others)
        beta, *_ = np.linalg.lstsq(Xd, X[:, j], rcond=None)
        pred = Xd @ beta
        resid = X[:, j] - pred
        tss = float(((X[:, j] - X[:, j].mean()) ** 2).sum())
        r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else 0.0
        vif = 1.0 / max(1.0 - r2, 1e-9)
        rows.append([names[j], "%.2f" % r2, "%.2f" % vif])
    rows.sort(key=lambda r: -float(r[2]))
    return rows


# --------------------------------------------------------------------------
# 4. Duan smearing 与反变换
# --------------------------------------------------------------------------

def duan_smearing(resid_log: np.ndarray) -> float:
    """Duan (1983) smearing 估计因子 E[exp(ε)]，用于把对数尺度预测还原到水平尺度。"""
    return float(np.mean(np.exp(resid_log)))


# --------------------------------------------------------------------------
# 5. 交叉验证
# --------------------------------------------------------------------------

def _metrics(y_log: np.ndarray, pred_log: np.ndarray, smearing: float) -> Dict[str, float]:
    resid = y_log - pred_log
    y_level = np.exp(y_log) * smearing
    p_level = np.exp(pred_log) * smearing
    denom = np.maximum(y_level, 1e-9)
    return {
        "n": float(y_log.size),
        "rmse_log": float(np.sqrt(np.mean(resid ** 2))),
        "mae_log": float(np.mean(np.abs(resid))),
        "rmse_level": float(np.sqrt(np.mean((y_level - p_level) ** 2))),
        "mape": float(np.mean(np.abs((y_level - p_level) / denom)) * 100.0),
        "medape": float(np.median(np.abs((y_level - p_level) / denom)) * 100.0),
        "r2": float(1.0 - np.sum(resid ** 2) / np.sum((y_log - y_log.mean()) ** 2)),
    }


def _fit_plain(X: np.ndarray, y: np.ndarray, family: str, lam: float) -> np.ndarray:
    Xd = _design(X)
    if family == "ridge":
        # 与 ridge_fit 保持一致：先标准化
        mu = X.mean(axis=0)
        sd = X.std(axis=0)
        sd = np.where(sd > 0, sd, 1.0)
        Xs = (X - mu) / sd
        ybar = y.mean()
        beta_s = np.linalg.solve(Xs.T @ Xs + lam * np.eye(Xs.shape[1]), Xs.T @ (y - ybar))
        beta = beta_s / sd
        b0 = ybar - mu @ beta
        return np.concatenate([[b0], beta])
    beta, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    return beta


def _predict(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return _design(X) @ beta


def random_cv(X: np.ndarray, y: np.ndarray, k: int = 5, family: str = "ols",
              lam: float = 1.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    idx = rng.permutation(y.size)
    folds = np.array_split(idx, k)
    preds = np.empty_like(y)
    for f in folds:
        train = np.setdiff1d(np.arange(y.size), f)
        beta = _fit_plain(X[train], y[train], family, lam)
        preds[f] = _predict(beta, X[f])
    sm = duan_smearing(y - preds)
    m = _metrics(y, preds, sm)
    m["smearing"] = sm
    return m, preds


def spatial_block_cv(X: np.ndarray, y: np.ndarray, block: np.ndarray, k: int = 5,
                     family: str = "ols", lam: float = 1.0):
    """空间分块交叉验证：整块留出，块内样本互不拆分。"""
    preds = np.full_like(y, np.nan)
    uniq = np.unique(block)
    for b in uniq:
        test = block == b
        if test.sum() == 0 or (~test).sum() < X.shape[1] + 2:
            continue
        beta = _fit_plain(X[~test], y[~test], family, lam)
        preds[test] = _predict(beta, X[test])
    ok = np.isfinite(preds)
    sm = duan_smearing(y[ok] - preds[ok])
    m = _metrics(y[ok], preds[ok], sm)
    m["smearing"] = sm
    m["n_blocks"] = float(len(uniq))
    return m, preds


# --------------------------------------------------------------------------
# 6. 总装
# --------------------------------------------------------------------------

@dataclass
class ModelResultBundle:
    codes: List[str]
    y_log: np.ndarray
    log_target: bool
    ols: ModelResult
    ridge: Optional[ModelResult]
    vif: List[List]
    cv_random: Dict[str, float]
    cv_spatial: Dict[str, float]
    fitted_log: np.ndarray
    resid_log: np.ndarray
    train_metrics: Dict[str, float] = field(default_factory=dict)
    oof_log: Optional[np.ndarray] = None


def fit_and_evaluate(
    X: np.ndarray,
    y_level: np.ndarray,
    codes: Sequence[str],
    block: np.ndarray,
    cfg: Dict,
) -> ModelResultBundle:
    log_target = bool(cfg.get("log_transform", True))
    y = np.log(np.maximum(y_level, 1e-9)) if log_target else np.asarray(y_level, dtype=float)
    lam = float(cfg.get("ridge_lambda", 1.0))
    seeds = int(cfg.get("seed", 0))

    ols = ols_fit(X, y, codes)
    ridge = ridge_fit(X, y, codes, lam=lam) if "ridge" in (cfg.get("family") or ["ols"]) else None

    fitted = _design(X) @ ols.coef
    resid = y - fitted
    sm = ols.smearing
    train = _metrics(y, fitted, sm)

    cv_cfg = cfg.get("cv") or {}
    k_rand = int(cv_cfg.get("random_folds", 5))
    k_spat = int(cv_cfg.get("spatial_folds", len(np.unique(block))))
    cv_rand, oof_rand = random_cv(X, y, k=k_rand, family="ols", seed=seeds)
    cv_spat, oof_spat = spatial_block_cv(X, y, block, k=k_spat, family="ols")

    return ModelResultBundle(
        codes=list(codes),
        y_log=y,
        log_target=log_target,
        ols=ols,
        ridge=ridge,
        vif=vif_table(X, codes),
        cv_random=cv_rand,
        cv_spatial=cv_spat,
        fitted_log=fitted,
        resid_log=resid,
        train_metrics=train,
        oof_log=oof_spat,
    )

# --------------------------------------------------------------------------
# 分区校准：按街道估计估值偏差，并用经验贝叶斯向 0 收缩
# --------------------------------------------------------------------------

@dataclass
class Calibration:
    """分组（街道）偏差估计结果。"""

    groups: Dict[str, Dict[str, float]]
    k: float
    global_mean: float

    def bias_of(self, name: str, default: float = 0.0) -> float:
        g = self.groups.get(str(name))
        return float(g["bias"]) if g else default

    def grade_of(self, name: str) -> str:
        g = self.groups.get(str(name))
        if not g:
            return "unknown"
        n, b = float(g["n"]), abs(float(g["bias"]))
        if n >= 12 and b <= 0.08 + 1e-9:
            return "ok"
        if n >= 6 and b <= 0.20 + 1e-9:
            return "warn"
        return "bad"

    def table(self) -> List[Dict]:
        out = []
        for name, g in sorted(self.groups.items(), key=lambda kv: -abs(kv[1]["bias"])):
            out.append({
                "name": name,
                "n": int(g["n"]),
                "raw": round(float(g["raw"]), 4),
                "bias": round(float(g["bias"]), 4),
                "sd": round(float(g["sd"]), 4),
                "grade": self.grade_of(name),
            })
        return out


def calibrate_block(groups, resid_log, k: float = 5.0) -> Calibration:
    """按分组估计对数残差均值，收缩后作为该组的估值校准量。

    收缩公式 bias = mean × n / (n + k)：样本少的组自动向 0 靠拢，
    避免仅凭两三条成交就大幅修正整条街道。
    """
    g = np.asarray(groups).astype(str)
    r = np.asarray(resid_log, dtype=float)
    ok = np.isfinite(r)
    out: Dict[str, Dict[str, float]] = {}
    if not ok.any():
        return Calibration(groups={}, k=float(k), global_mean=0.0)
    for name in np.unique(g[ok]):
        vals = r[ok & (g == name)]
        n = int(vals.size)
        if n == 0:
            continue
        mean = float(vals.mean())
        sd = float(vals.std(ddof=1)) if n > 1 else 0.0
        out[str(name)] = {
            "n": float(n),
            "raw": mean,
            "bias": mean * n / (n + k),
            "sd": sd,
        }
    gm = float(r[ok].mean())
    return Calibration(groups=out, k=float(k), global_mean=gm)
