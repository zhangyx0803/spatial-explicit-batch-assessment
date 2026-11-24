# -*- coding: utf-8 -*-
"""空间算子库。

每个算子统一签名：func(ctx, ds, spec) -> {输出名: (n_units,) 数组}
算子只负责"怎么算"，参数与输入由声明式配置提供，引擎负责调度与缓存。
"""

from __future__ import annotations

from typing import Callable, Dict, List

import numpy as np

from .datamodel import Dataset
from .net import CSRGraph, snap_points

__all__ = ["OP_FUNCS", "RuntimeContext", "decay_fn"]

# 衰减函数

def decay_fn(imp: Dict, x: np.ndarray) -> np.ndarray:
    """按配置生成衰减权重。x 为距离或时间，sigma/beta 的量纲须与 x 一致。"""
    kind = imp.get("type", "exponential")
    if kind == "exponential":
        beta = float(imp.get("beta", 0.08))
        return np.exp(-beta * x)
    if kind == "power":
        beta = float(imp.get("beta", 1.0))
        return np.power(np.maximum(x, 1e-6), -beta)
    if kind == "gaussian":
        sigma = float(imp.get("sigma", imp.get("sigma_min", 1.0)))
        return np.exp(-0.5 * (x / max(sigma, 1e-9)) ** 2)
    raise ValueError("未知衰减类型：%s" % kind)

def _decay_param(imp: Dict, x: np.ndarray) -> Dict:
    """高斯衰减若以 _min 命名，则在此处统一量纲。"""
    out = dict(imp)
    if out.get("type") == "gaussian":
        if "sigma" not in out and "sigma_min" in out:
            out["sigma"] = float(out["sigma_min"])
    return out

# 运行期上下文：图层解析、吸附缓存、图缓存

class RuntimeContext:
    def __init__(self, ds: Dataset):
        self.ds = ds
        g = ds.grid
        cx, cy = g.centroid(ds.units.ix, ds.units.iy)
        self.unit_x = cx
        self.unit_y = cy
        self._graphs: Dict[str, CSRGraph] = {}
        self._snap_unit: Dict[str, object] = {}
        self._weights: Dict[tuple, np.ndarray] = {}
        self.snap_failures: Dict[str, float] = {}
        self.snap_mean_dist: Dict[str, float] = {}

    # 图
    def graph(self, layer_id: str) -> CSRGraph:
        if layer_id not in self._graphs:
            lyr = self.ds.layer(layer_id)
            if lyr.layer_type != "network":
                raise ValueError("图层 %s 不是网络图层" % layer_id)
            self._graphs[layer_id] = CSRGraph(lyr.nodes.shape[0], lyr.edges, lyr.nodes)
        return self._graphs[layer_id]

    def w(self, layer_id: str, mode: str) -> np.ndarray:
        key = (layer_id, mode)
        if key not in self._weights:
            self._weights[key] = self.graph(layer_id).weights(mode)
        return self._weights[key]

    # 吸附
    def snap_units(self, layer_id: str, max_dist_m: float = 300.0):
        key = (layer_id, round(max_dist_m, 3))
        if key not in self._snap_unit:
            g = self.graph(layer_id)
            r = snap_points(self.unit_x, self.unit_y, g.node_xy, max_dist_m)
            self._snap_unit[key] = r
            self.snap_failures[layer_id] = r.failed_share
            self.snap_mean_dist[layer_id] = r.mean_dist
        return self._snap_unit[key]

    def snap_layer(self, layer_id: str, max_dist_m: float = 300.0):
        lyr = self.ds.layer(layer_id)
        g = self.graph("road_net")
        return snap_points(lyr.x, lyr.y, g.node_xy, max_dist_m)

def _unit_mask(ds: Dataset, layer_id: str) -> np.ndarray:
    return np.ones(ds.n_units, dtype=bool)

# 几何辅助（本版本：点集 / 轴对齐矩形）

def _point_dist_matrix(px: np.ndarray, py: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """返回 (n_points, n_units) 的欧氏距离矩阵。"""
    out = np.empty((px.size, xs.size), dtype=float)
    for k in range(px.size):
        out[k] = np.hypot(xs - px[k], ys - py[k])
    return out

def _rect_dist(rect: tuple, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    rx, ry, rw, rh = rect
    dx = np.maximum.reduce([xs - (rx + rw), rx - xs, np.zeros_like(xs)])
    dy = np.maximum.reduce([ys - (ry + rh), ry - ys, np.zeros_like(ys)])
    return np.hypot(dx, dy)

def _poly_dist(rects: List[tuple], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    d = np.full(xs.size, np.inf)
    for r in rects:
        d = np.minimum(d, _rect_dist(r, xs, ys))
    return d

def _disc_share(rects: List[tuple], xs: np.ndarray, ys: np.ndarray, radius: float,
                samples: int = 40, seed: int = 11) -> np.ndarray:
    """用圆内均匀采样估计"缓冲区内被多边形覆盖的面积占比"。"""
    rng = np.random.default_rng(seed)
    ang = rng.uniform(0, 2 * np.pi, samples)
    rad = radius * np.sqrt(rng.uniform(0, 1, samples))
    out = np.zeros(xs.size)
    for s in range(samples):
        px = xs + rad[s] * np.cos(ang[s])
        py = ys + rad[s] * np.sin(ang[s])
        hit = np.zeros(xs.size, dtype=bool)
        for (rx, ry, rw, rh) in rects:
            hit |= (px >= rx) & (px <= rx + rw) & (py >= ry) & (py <= ry + rh)
        out += hit
    return out / samples

# 算子实现

def op_network_shortest_path(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    net_id = spec.inputs["network"]
    dst_id = spec.inputs["destinations"]
    mode = spec.params.get("mode", "drive")
    snap_par = spec.params.get("snap") or {}
    maxd = float(snap_par.get("max_dist_m", 300.0))
    turn = float(spec.params.get("turn_penalty_min", 0.0) or 0.0)

    g = ctx.graph(net_id)
    wlen = g.weights("walk") * 0.0 + g.edge_len          # 纯长度（m）
    wtime = ctx.w(net_id, mode)

    units_snap = ctx.snap_units(net_id, maxd)
    dst = ds.layer(dst_id)
    dst_snap = snap_points(dst.x, dst.y, g.node_xy, 1e12)

    unit_nodes = units_snap.node
    best_time = np.full(ds.n_units, np.inf)
    best_dist = np.full(ds.n_units, np.inf)

    if turn > 0.0 and dst_snap.node.size == 1:
        # 需要转向约束时走自建边扩展图（scipy 不支持转向关系）
        src = int(dst_snap.node[0])
        dt = g.dijkstra_edge_expanded(src, wtime, turn_penalty_min=turn)
        dl = g.dijkstra(src, wlen)
        best_time = dt[unit_nodes]
        best_dist = dl[unit_nodes]
    else:
        # 常规情形：多源批量最短路，一次算完所有目的地
        for (a, b), buf in g.iter_dijkstra_many(np.unique(dst_snap.node), wtime, chunk=16):
            best_time = np.minimum(best_time, buf[:, unit_nodes].min(axis=0))
        for (a, b), buf in g.iter_dijkstra_many(np.unique(dst_snap.node), wlen, chunk=16):
            best_dist = np.minimum(best_dist, buf[:, unit_nodes].min(axis=0))

    ok = units_snap.ok
    t_fill = np.nanmedian(best_time[np.isfinite(best_time)]) if np.isfinite(best_time).any() else 0.0
    best_time = np.where(ok & np.isfinite(best_time), best_time, t_fill)
    best_dist = np.where(ok & np.isfinite(best_dist), best_dist, t_fill * 300.0)
    return {"dist_m": best_dist, "t_min": best_time}

def op_network_isochrone(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    net_id = spec.inputs["network"]
    dst_id = spec.inputs["destinations"]
    mode = spec.params.get("mode", "walk")
    thresholds = [float(t) for t in (spec.params.get("thresholds_min") or [15])]
    tmax = max(thresholds)
    snap_par = spec.params.get("snap") or {}
    maxd = float(snap_par.get("max_dist_m", 300.0))

    g = ctx.graph(net_id)
    w = ctx.w(net_id, mode)
    units_snap = ctx.snap_units(net_id, maxd)
    dst = ds.layer(dst_id)
    dst_snap = snap_points(dst.x, dst.y, g.node_xy, 1e12)

    unit_nodes = units_snap.node
    cnt = np.zeros(ds.n_units)
    nearest = np.full(ds.n_units, np.inf)
    for (a, b), buf in g.iter_dijkstra_many(np.unique(dst_snap.node), w, limit=tmax, chunk=16):
        sub = buf[:, unit_nodes]
        cnt += np.isfinite(sub).sum(axis=0).astype(float)
        nearest = np.minimum(nearest, sub.min(axis=0))
    nearest = np.where(np.isfinite(nearest), nearest, tmax * 2)
    return {"t_min": nearest, "n_reached": cnt}

def op_gravity_access(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    imp = _decay_param(spec.params["impedance"], np.zeros(1))
    dist_ref = spec.inputs.get("dist")

    if isinstance(dist_ref, str) and dist_ref.startswith("factor:"):
        # 单一目的地的重力可达性：mass * f(dist)
        code = dist_ref.split(":", 1)[1]
        d = ds.attrs[code]
        mass = float(spec.params.get("mass", 1.0))
        return {"index": mass * decay_fn(imp, np.maximum(d, 1e-9))}

    # 多点机会的重力可达性（欧氏距离）
    lyr = ds.layer(spec.inputs["opportunity"])
    w = lyr.attrs.get("weight", np.ones(lyr.x.size))
    d = _point_dist_matrix(lyr.x, lyr.y, ctx.unit_x, ctx.unit_y)
    f = decay_fn(imp, np.maximum(d, 1e-9))
    return {"index": (f * w[:, None]).sum(axis=0)}

def op_two_step_floating_catchment(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    sup_id = spec.inputs["supply"]
    demand_ref = spec.inputs["demand"]
    net_id = spec.inputs["network"]
    tmax = float(spec.params["threshold_min"])
    dec = _decay_param(spec.params["decay"], np.zeros(1))
    snap_par = spec.params.get("snap") or {}
    maxd = float(snap_par.get("max_dist_m", 300.0))

    g = ctx.graph(net_id)
    # 2SFCA 的出行模式由配置给出（缺省步行），阻抗取该模式的速度表
    w = ctx.w(net_id, spec.params.get("mode", "walk"))
    units_snap = ctx.snap_units(net_id, maxd)

    lyr = ds.layer(sup_id)
    S = np.asarray(lyr.attrs.get("capacity", np.ones(lyr.x.size)), dtype=float)
    if isinstance(demand_ref, str) and demand_ref.startswith("field:"):
        field = demand_ref.split(":", 1)[1]
        P = _unit_field(ds, field).astype(float)
    else:
        P = ds.layer(demand_ref).attrs["population"].astype(float)

    sup_snap = snap_points(lyr.x, lyr.y, g.node_xy, 1e12)
    unit_nodes = units_snap.node
    Fdec = decay_fn(dec, np.maximum(np.zeros(1), 1e-9))  # 仅为取函数

    # 第一遍：算每个设施的供需比分母 Σ P*f(t)
    denom = np.zeros(lyr.x.size)
    for (a, b), buf in g.iter_dijkstra_many(sup_snap.node, w, limit=tmax, chunk=16):
        sub = buf[:, unit_nodes]
        F = np.where(np.isfinite(sub), decay_fn(dec, np.maximum(sub, 1e-9)), 0.0)
        denom[a:b] = (F * P[None, :]).sum(axis=1)

    R = np.where(denom > 0, S / np.maximum(denom, 1e-12), 0.0)

    # 第二遍：按需求点聚合 Σ R*f(t)
    A = np.zeros(ds.n_units)
    for (a, b), buf in g.iter_dijkstra_many(sup_snap.node, w, limit=tmax, chunk=16):
        sub = buf[:, unit_nodes]
        F = np.where(np.isfinite(sub), decay_fn(dec, np.maximum(sub, 1e-9)), 0.0)
        A += (R[a:b, None] * F).sum(axis=0)
    return {"sfca_index": A}

def op_distance_decay(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    code = spec.inputs["dist"].split(":", 1)[1]
    d = ds.attrs[code]
    imp = _decay_param(spec.params["impedance"], np.zeros(1))
    return {"value": decay_fn(imp, np.maximum(d, 1e-9))}

def op_buffer_overlay(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    lyr = ds.layer(spec.inputs["layer"])
    radius = float(spec.params["radius_m"])
    stat = spec.params["stat"]
    xs, ys = ctx.unit_x, ctx.unit_y

    if lyr.layer_type == "point":
        w = lyr.attrs.get("weight", np.ones(lyr.x.size))
        d = _point_dist_matrix(lyr.x, lyr.y, xs, ys)
        inside = d <= radius
        if stat == "count":
            return {"value": inside.sum(axis=0).astype(float)}
        if stat == "weighted_count":
            return {"value": (inside * w[:, None]).sum(axis=0)}
        raise ValueError("buffer_overlay 不支持的统计量：%s" % stat)

    if lyr.layer_type == "polygon":
        if stat not in ("area_share",):
            raise ValueError("多边形缓冲只支持 area_share")
        return {"value": _disc_share(lyr.polygons, xs, ys, radius)}

    raise ValueError("buffer_overlay 不支持图层类型 %s" % lyr.layer_type)

def op_spatial_join_agg(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    lyr = ds.layer(spec.inputs["layer"])
    stat = spec.params["stat"]
    xs, ys = ctx.unit_x, ctx.unit_y

    if lyr.layer_type == "polygon":
        d = _poly_dist(lyr.polygons, xs, ys)
    elif lyr.layer_type == "point":
        d = _point_dist_matrix(lyr.x, lyr.y, xs, ys).min(axis=0)
    else:
        raise ValueError("spatial_join_agg 不支持图层类型 %s" % lyr.layer_type)

    if stat == "nearest_distance":
        return {"value": d}
    raise ValueError("spatial_join_agg 不支持的统计量：%s" % stat)

def op_kernel_density(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    lyr = ds.layer(spec.inputs["layer"])
    h = float(spec.params["bandwidth_m"])
    w = lyr.attrs.get("weight", np.ones(lyr.x.size))
    d = _point_dist_matrix(lyr.x, lyr.y, ctx.unit_x, ctx.unit_y)
    k = np.exp(-0.5 * (d / h) ** 2) / (2 * np.pi * h * h) * 1e6
    return {"value": (k * w[:, None]).sum(axis=0)}

def op_network_topology(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    net_id = spec.inputs["network"]
    radius = float(spec.params["radius_m"])
    stat = spec.params["stat"]
    g = ctx.graph(net_id)

    deg = np.diff(g.indptr) + np.diff(g.in_indptr)
    is_inter = deg >= 3
    is_dead = deg <= 1
    node_xy = g.node_xy

    inter = int(is_inter.sum())
    dead = int(is_dead.sum())
    inter_xy = node_xy[is_inter]
    dead_xy = node_xy[is_dead]

    def density(sub: np.ndarray) -> np.ndarray:
        out = np.zeros(ds.n_units)
        for k in range(sub.shape[0]):
            d = np.hypot(ctx.unit_x - sub[k, 0], ctx.unit_y - sub[k, 1])
            out += (d <= radius)
        area_km2 = np.pi * (radius / 1000.0) ** 2
        return out / area_km2

    if stat == "intersection_density":
        return {"intersection_density": density(inter_xy)}
    if stat == "deadend_ratio":
        out = np.zeros(ds.n_units)
        for k in range(dead_xy.shape[0]):
            d = np.hypot(ctx.unit_x - dead_xy[k, 0], ctx.unit_y - dead_xy[k, 1])
            out += (d <= radius)
        tot = np.zeros(ds.n_units)
        for k in range(node_xy.shape[0]):
            d = np.hypot(ctx.unit_x - node_xy[k, 0], ctx.unit_y - node_xy[k, 1])
            tot += (d <= radius)
        return {"deadend_ratio": out / np.maximum(tot, 1.0)}
    raise ValueError("network_topology 不支持的统计量：%s" % stat)

def op_raster_extract(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    lyr = ds.layer(spec.inputs["raster"])
    v = lyr.value
    nx, ny = v.shape
    cx, cy = ctx.unit_x, ctx.unit_y
    ix = np.clip((cx / ds.grid.cell).astype(int), 0, nx - 1)
    iy = np.clip((cy / ds.grid.cell).astype(int), 0, ny - 1)
    return {"value": v[ix, iy]}

def _unit_field(ds: Dataset, name: str) -> np.ndarray:
    if name in ds.unit_attrs:
        return ds.unit_attrs[name]
    if hasattr(ds.units, name):
        return np.asarray(getattr(ds.units, name), dtype=float)
    raise KeyError("未知单元字段：%s" % name)

def op_attribute(ctx: RuntimeContext, ds: Dataset, spec) -> Dict[str, np.ndarray]:
    ref = spec.inputs["field"]
    name = ref.split(":", 1)[1] if ":" in ref else ref
    return {"value": _unit_field(ds, name).astype(float)}

OP_FUNCS: Dict[str, Callable] = {
    "network_shortest_path": op_network_shortest_path,
    "network_isochrone": op_network_isochrone,
    "gravity_access": op_gravity_access,
    "two_step_floating_catchment": op_two_step_floating_catchment,
    "distance_decay": op_distance_decay,
    "buffer_overlay": op_buffer_overlay,
    "spatial_join_agg": op_spatial_join_agg,
    "kernel_density": op_kernel_density,
    "network_topology": op_network_topology,
    "raster_extract": op_raster_extract,
    "attribute": op_attribute,
}
