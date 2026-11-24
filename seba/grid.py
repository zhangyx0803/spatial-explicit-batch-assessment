# -*- coding: utf-8 -*-
"""演示研究区与盲合成交易库。

研究区：40 × 40 规则格网，每格 250 m，合计 10 km × 10 km（1600 个评估单元）。
路网：与格网同构的棋盘路网，按主干道 / 次干道 / 支路分等级赋速，含单向边与尽端支路。

关于价格生成（重要）：
价格由一个潜在过程生成，只依赖"地理事实"本身（到 CBD 的通勤时间、到地铁的步行距离、
绿地率、商业密度、人口密度、容积率、噪声），外加一个平滑的空间随机场和重尾噪声。
该过程与因子引擎互不知道对方：引擎随后从同一份地理数据里把因子算出来，
模型能否恢复系数、能否把两个无关的安慰剂因子压到 0，就是对方法的真实检验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np

from .datamodel import Dataset, Grid, LayerData, ObsTable, UnitTable
from .net import CSRGraph, snap_points

__all__ = ["build_demo_dataset", "DemoScene"]


@dataclass
class DemoScene:
    dataset: Dataset
    graph_drive: CSRGraph
    graph_walk: CSRGraph
    truth: Dict[str, float]


def _smooth_field(nx: int, ny: int, rng: np.random.Generator, n_wave: int = 4) -> np.ndarray:
    """几组二维正弦叠加出的平滑场，用于空间随机效应。"""
    xx, yy = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
    xx = xx / max(nx - 1, 1)
    yy = yy / max(ny - 1, 1)
    out = np.zeros((nx, ny), dtype=float)
    for _ in range(n_wave):
        fx = rng.uniform(0.6, 2.2)
        fy = rng.uniform(0.6, 2.2)
        ph = rng.uniform(0, 2 * np.pi)
        amp = rng.normal(0, 1)
        out += amp * np.sin(2 * np.pi * (fx * xx + fy * yy) + ph)
    out -= out.mean()
    sd = out.std()
    return out / sd if sd > 0 else out


def _z(v: np.ndarray) -> np.ndarray:
    sd = v.std()
    return (v - v.mean()) / sd if sd > 0 else v * 0.0


def build_demo_dataset(seed: int = 20261117, nx: int = 40, ny: int = 40, cell: float = 250.0) -> DemoScene:
    rng = np.random.default_rng(seed)
    grid = Grid(nx=nx, ny=ny, cell=cell)

    # 路网
    # 节点：格点 (i, j)，i∈[0, nx]，j∈[0, ny]
    node_ij = np.array([(i, j) for j in range(ny + 1) for i in range(nx + 1)], dtype=int)
    node_xy = np.column_stack([node_ij[:, 0] * cell, node_ij[:, 1] * cell]).astype(float)
    idx = {(int(i), int(j)): k for k, (i, j) in enumerate(node_ij)}

    edges = []
    # 横向边（沿 i 方向），等级由所在 j 决定
    for j in range(ny + 1):
        cls = 1 if j % 10 == 0 else (2 if j % 5 == 0 else 3)
        for i in range(nx):
            u, v = idx[(i, j)], idx[(i + 1, j)]
            edges.append((u, v, cell, cls, 0))
    # 纵向边（沿 j 方向），等级由所在 i 决定
    for i in range(nx + 1):
        cls = 1 if i % 10 == 0 else (2 if i % 5 == 0 else 3)
        for j in range(ny):
            u, v = idx[(i, j)], idx[(i, j + 1)]
            edges.append((u, v, cell, cls, 0))

    # 尽端支路：从部分节点伸出一段 120 m 的死胡同
    n_spur = 90
    extra_xy = []
    for _ in range(n_spur):
        u = int(rng.integers(0, len(node_ij)))
        ang = rng.uniform(0, 2 * np.pi)
        px = node_xy[u, 0] + 120.0 * np.cos(ang)
        py = node_xy[u, 1] + 120.0 * np.sin(ang)
        v = len(node_xy) + len(extra_xy)
        extra_xy.append((px, py))
        edges.append((u, v, 120.0, 3, 0))
    if extra_xy:
        node_xy = np.vstack([node_xy, np.array(extra_xy, dtype=float)])

    edges = np.array(edges, dtype=float)
    # 少量单向边（只在次干道与支路）
    mask = (edges[:, 3] > 1) & (rng.random(edges.shape[0]) < 0.08)
    edges[mask, 4] = 1.0

    graph_drive = CSRGraph(node_xy.shape[0], edges, node_xy)
    graph_walk = graph_drive  # 同一张拓扑，阻抗按模式不同

    # 评估单元
    ix = np.repeat(np.arange(nx), ny)
    iy = np.tile(np.arange(ny), nx)
    n_units = ix.size
    cx, cy = grid.centroid(ix, iy)

    unit_id = np.array(["U%05d" % (k + 1) for k in range(n_units)])
    # 行政区划：4×4 个统计单元（用于分区残差聚合与失配板块识别）
    admin_code = np.array(["3101%02d" % (int(i) * 4 + int(j) // 10 + 1) for i, j in zip(ix // 10, iy)])
    area = np.full(n_units, grid.area, dtype=float)

    # 图层：POI 与设施
    def jitter_along_trunk(n: int, offset_sd: float = 90.0) -> tuple:
        """沿主干道两侧撒点（商业沿街分布）。"""
        lines = rng.choice([2, 4, 6, 8], size=n) * 5 * cell   # 每 5 格一条次干道以上
        along = rng.uniform(0, nx * cell, size=n)
        off = rng.normal(0, offset_sd, size=n)
        return along + off, lines + rng.normal(0, offset_sd, size=n)

    pcom_x, pcom_y = jitter_along_trunk(520)
    poi_com = LayerData(
        layer_id="poi_com", layer_type="point", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        fields=["weight"], x=pcom_x, y=pcom_y,
        attrs={"weight": rng.uniform(0.5, 3.0, 520)},
    )

    metro_slots = [(2, 2), (14, 3), (26, 2), (6, 12), (18, 16), (32, 11), (10, 24), (24, 27)]
    metro_xy = np.array([(a * 5 * cell, b * 5 * cell) for a, b in metro_slots], dtype=float)
    poi_metro = LayerData(
        layer_id="poi_metro", layer_type="point", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        fields=[], x=metro_xy[:, 0], y=metro_xy[:, 1],
    )

    n_school = 18
    school_xy = np.column_stack([rng.uniform(0, nx * cell, n_school), rng.uniform(0, ny * cell, n_school)])
    poi_school = LayerData(
        layer_id="poi_school", layer_type="point", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        fields=["capacity"], x=school_xy[:, 0], y=school_xy[:, 1],
        attrs={"capacity": rng.uniform(600, 2200, n_school)},
    )

    n_hosp = 7
    hosp_xy = np.column_stack([rng.uniform(0, nx * cell, n_hosp), rng.uniform(0, ny * cell, n_hosp)])
    poi_hosp = LayerData(
        layer_id="poi_hospital", layer_type="point", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        fields=["capacity"], x=hosp_xy[:, 0], y=hosp_xy[:, 1],
        attrs={"capacity": rng.uniform(200, 1200, n_hosp)},
    )

    n_bus = 110
    bus_xy = np.column_stack([rng.uniform(0, nx * cell, n_bus), rng.uniform(0, ny * cell, n_bus)])
    poi_bus = LayerData(
        layer_id="poi_bus", layer_type="point", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        fields=[], x=bus_xy[:, 0], y=bus_xy[:, 1],
    )

    # 公园：轴对齐矩形
    parks = []
    for _ in range(12):
        w = rng.uniform(400, 900)
        h = rng.uniform(400, 900)
        parks.append((rng.uniform(0, nx * cell - w), rng.uniform(0, ny * cell - h), w, h))
    layer_park = LayerData(
        layer_id="layer_park", layer_type="polygon", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        polygons=parks,
    )

    # 水系：一条斜向带状（用若干矩形拼）
    water = []
    for k in range(nx):
        yy = 0.18 * ny * cell + 0.42 * k * cell
        water.append((k * cell, yy, cell, 260.0))
    layer_water = LayerData(
        layer_id="layer_water", layer_type="polygon", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        polygons=water,
    )

    # 栅格图层
    pop = np.exp(-(((np.arange(nx)[:, None] - nx * 0.45) / (nx * 0.22)) ** 2
                   + ((np.arange(ny)[None, :] - ny * 0.5) / (ny * 0.25)) ** 2))
    pop = pop / pop.max() * 0.9 + 0.1 + rng.normal(0, 0.03, (nx, ny))
    pop = np.clip(pop, 0.02, None)
    layer_pop = LayerData(
        layer_id="layer_pop", layer_type="raster", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        value=pop, transform=(grid.x0, grid.cell, grid.y0, grid.cell),
    )

    far_base = 1.2 + 1.8 * pop
    far = np.clip(far_base + 0.5 * _smooth_field(nx, ny, rng), 1.0, 4.5)
    layer_far = LayerData(
        layer_id="layer_far", layer_type="raster", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        value=far, transform=(grid.x0, grid.cell, grid.y0, grid.cell),
    )

    built = np.clip(0.18 + 0.30 * pop + 0.05 * _smooth_field(nx, ny, rng), 0.08, 0.62)
    layer_built = LayerData(
        layer_id="layer_built", layer_type="raster", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        value=built, transform=(grid.x0, grid.cell, grid.y0, grid.cell),
    )

    # 夜间噪声：靠近主干道更高（主干道位于 10 格整数倍处）
    xs_c = (np.arange(nx) + 0.5) * cell
    ys_c = (np.arange(ny) + 0.5) * cell
    trunk_step = 10 * cell
    dx_trunk = np.abs(((xs_c + trunk_step / 2) % trunk_step) - trunk_step / 2)
    dy_trunk = np.abs(((ys_c + trunk_step / 2) % trunk_step) - trunk_step / 2)
    dist_trunk = np.minimum(dx_trunk[:, None], dy_trunk[None, :])
    noise = 68.0 - 22.0 * np.exp(-dist_trunk / 450.0) + rng.normal(0, 1.2, (nx, ny))
    layer_noise = LayerData(
        layer_id="layer_noise", layer_type="raster", crs="CGCS2000", asof_date="2025-06-30", version="v1",
        value=noise, transform=(grid.x0, grid.cell, grid.y0, grid.cell),
    )

    # CBD：中心偏东北
    cbd_xy = np.array([0.62 * nx * cell, 0.66 * ny * cell])

    layers = {
        "road_net": LayerData(
            layer_id="road_net", layer_type="network", crs="CGCS2000", asof_date="2025-06-30", version="v1",
            fields=["length", "speed_class", "oneway"], nodes=node_xy, edges=edges,
            aux_meta=graph_drive.connectivity(),
        ),
        "poi_cbd": LayerData(
            layer_id="poi_cbd", layer_type="point", crs="CGCS2000", asof_date="2025-06-30", version="v1",
            fields=[], x=np.array([float(cbd_xy[0])]), y=np.array([float(cbd_xy[1])]),
        ),
        "poi_com": poi_com,
        "poi_metro": poi_metro,
        "poi_school": poi_school,
        "poi_hospital": poi_hosp,
        "poi_bus": poi_bus,
        "layer_park": layer_park,
        "layer_water": layer_water,
        "layer_pop": layer_pop,
        "layer_far": layer_far,
        "layer_built": layer_built,
        "layer_noise": layer_noise,
    }

    # 潜在过程（生成价格用）
    snap_unit = snap_points(cx, cy, node_xy, max_dist_m=300.0)
    w_drive = graph_drive.weights("drive")
    w_walk = graph_drive.weights("walk")

    # CBD 锚点
    cbd_node = int(snap_points(cbd_xy[None, 0], cbd_xy[None, 1], node_xy, 1e9).node[0])
    t_cbd = graph_drive.dijkstra(cbd_node, w_drive)[snap_unit.node]

    # 地铁步行距离（多源反向：从每个站走路网，再取最小）
    d_metro = np.full(n_units, np.inf)
    for k in range(metro_xy.shape[0]):
        sn = int(snap_points(metro_xy[k:k + 1, 0], metro_xy[k:k + 1, 1], node_xy, 1e9).node[0])
        dd = graph_walk.dijkstra(sn, w_walk)[snap_unit.node]
        d_metro = np.minimum(d_metro, dd)

    # 绿地率（500 m 缓冲，用栅格近似统计公园覆盖）
    def poly_cover(xs: np.ndarray, ys: np.ndarray, rects, radius: float, samples: int = 24) -> np.ndarray:
        rng2 = np.random.default_rng(7)
        ang = rng2.uniform(0, 2 * np.pi, samples)
        rad = radius * np.sqrt(rng2.uniform(0, 1, samples))
        out = np.zeros(xs.shape[0])
        for s in range(samples):
            px = xs + rad[s] * np.cos(ang[s])
            py = ys + rad[s] * np.sin(ang[s])
            hit = np.zeros(xs.shape[0], dtype=bool)
            for (rx, ry, rw, rh) in rects:
                hit |= (px >= rx) & (px <= rx + rw) & (py >= ry) & (py <= ry + rh)
            out += hit
        return out / samples

    green = poly_cover(cx, cy, parks, 500.0)

    def count_within(px: np.ndarray, py: np.ndarray, radius: float) -> np.ndarray:
        out = np.zeros(px.shape[0])
        for s in range(px.shape[0]):
            d = np.hypot(pcom_x - px[s], pcom_y - py[s])
            out[s] = float((d <= radius).sum())
        return out

    poi_1km = count_within(cx, cy, 1000.0)

    pop_u = pop[ix, iy]
    far_u = far[ix, iy]
    noise_u = noise[ix, iy]

    t_cbd = np.where(np.isfinite(t_cbd), t_cbd, np.nanmedian(t_cbd))
    d_metro = np.where(np.isfinite(d_metro), d_metro, np.nanmedian(d_metro))

    spatial = _smooth_field(nx, ny, rng)[ix, iy]

    z = (
        -0.42 * _z(np.log1p(t_cbd))
        - 0.30 * _z(np.log1p(d_metro))
        + 0.26 * _z(green)
        + 0.22 * _z(np.log1p(poi_1km))
        + 0.18 * _z(pop_u)
        + 0.14 * _z(far_u)
        - 0.20 * _z(noise_u)
        + 0.15 * spatial
    )
    # 重尾噪声：t 分布
    noise_eps = rng.standard_t(df=5, size=n_units) * 0.09
    log_price_pm2 = np.log(58000.0) + z + noise_eps
    price_pm2 = np.exp(log_price_pm2)

    # 成交样本（55% 单元有成交）
    has_obs = rng.random(n_units) < 0.55
    obs_idx = np.nonzero(has_obs)[0]
    n_obs = obs_idx.size
    deal_year = rng.choice([2023, 2024, 2025], size=n_obs, p=[0.2, 0.35, 0.45])
    deal_month = rng.integers(1, 13, size=n_obs)
    deal_date = np.array(["%04d-%02d-15" % (y, m) for y, m in zip(deal_year, deal_month)])
    # 时间趋势：2023 → 2025 累计上涨约 8%
    trend = 1.0 + 0.04 * (deal_year - 2023)
    unit_price_obs = price_pm2[obs_idx] * trend
    unit_area = 90.0
    price_obs = unit_price_obs * unit_area

    obs = ObsTable(
        unit_idx=obs_idx,
        price=price_obs,
        unit_price=unit_price_obs,
        deal_date=deal_date,
        price_type=np.array(["deal"] * n_obs),
        source=np.array(["demo"] * n_obs),
        weight=1.0 / trend,
    )

    units = UnitTable(
        unit_id=unit_id,
        ix=ix,
        iy=iy,
        area=area,
        admin_code=admin_code,
        use_type=np.array(["住宅"] * n_units),
        population=(pop_u * 4200).round(0),
        asof_date="2025-06-30",
        x=cx, y=cy,
    )

    unit_attrs = {
        "far": far_u,
        "built_density": built[ix, iy],
        "floor_ratio": np.clip(rng.beta(2.4, 2.0, n_units), 0.05, 0.98),
        "placebo_1": rng.normal(0, 1, n_units),
        "placebo_2": rng.normal(0, 1, n_units),
        "pop_density": pop_u * 4200,
    }

    ds = Dataset(
        grid=grid,
        units=units,
        obs=obs,
        layers=layers,
        crs="CGCS2000",
        project_name="演示区（合成数据）",
        unit_attrs=unit_attrs,
    )

    truth = {
        "A 组有效因子数": 7,
        "B 组安慰剂因子数": 2,
        "空间随机效应振幅": 0.15,
        "重尾噪声（t5）标度": 0.09,
        "成交样本量": float(n_obs),
    }
    return DemoScene(dataset=ds, graph_drive=graph_drive, graph_walk=graph_walk, truth=truth)
