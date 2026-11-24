# -*- coding: utf-8 -*-
"""内部数据契约：unit / attr / obs / layer 四张表。

三张主表描述"评什么、有什么、卖了多少"；图层注册表描述"因子运算从哪里取数据"。
几何在本版本中用规则格网表达（单元 = 格网单元），接口保持与矢量版一致：
单元提供 bbox、centroid、area 三个几何访问器，换成 geopandas 时只需替换本模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

__all__ = ["Grid", "UnitTable", "ObsTable", "LayerData", "Dataset"]

@dataclass
class Grid:
    """规则格网研究区（投影坐标系，单位 m）。"""

    nx: int
    ny: int
    cell: float
    x0: float = 0.0
    y0: float = 0.0

    @property
    def n_units(self) -> int:
        return self.nx * self.ny

    @property
    def area(self) -> float:
        return float(self.cell) ** 2

    def centroid(self, ix: np.ndarray, iy: np.ndarray) -> tuple:
        x = self.x0 + (np.asarray(ix, dtype=float) + 0.5) * self.cell
        y = self.y0 + (np.asarray(iy, dtype=float) + 0.5) * self.cell
        return x, y

    def bbox(self, ix: int, iy: int) -> tuple:
        x0 = self.x0 + ix * self.cell
        y0 = self.y0 + iy * self.cell
        return (x0, y0, x0 + self.cell, y0 + self.cell)

    @property
    def extent(self) -> tuple:
        return (
            self.x0,
            self.y0,
            self.x0 + self.nx * self.cell,
            self.y0 + self.ny * self.cell,
        )

@dataclass
class UnitTable:
    """表 1：评估单元。x / y 为单元中心坐标（米），地图与空间权重都用它。"""

    unit_id: np.ndarray
    ix: np.ndarray
    iy: np.ndarray
    area: np.ndarray
    admin_code: np.ndarray
    use_type: np.ndarray
    population: np.ndarray
    asof_date: str
    x: Optional[np.ndarray] = None
    y: Optional[np.ndarray] = None
    name: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        if self.x is None or self.y is None:
            self.x = np.zeros(len(self.unit_id), dtype=float)
            self.y = np.zeros(len(self.unit_id), dtype=float)

    def __len__(self) -> int:
        return int(self.unit_id.shape[0])

    def index_of(self, unit_id: str) -> int:
        hit = np.nonzero(self.unit_id == unit_id)[0]
        if hit.size == 0:
            raise KeyError("未知单元：%s" % unit_id)
        return int(hit[0])

@dataclass
class ObsTable:
    """表 3：成交观测。"""

    unit_idx: np.ndarray
    price: np.ndarray          # 总价（元）
    unit_price: np.ndarray     # 单价（元/m²），建模用
    deal_date: np.ndarray
    price_type: np.ndarray
    source: np.ndarray
    weight: np.ndarray

    def __len__(self) -> int:
        return int(self.price.shape[0])

@dataclass
class LayerData:
    """表 4：辅图层注册表的一条记录 + 实际数据。"""

    layer_id: str
    layer_type: str            # network / point / polygon / raster
    crs: str
    asof_date: str
    version: str
    fields: List[str] = field(default_factory=list)
    aux_meta: Dict[str, Any] = field(default_factory=dict)
    # point / polygon / network 的坐标；raster 用 value + transform
    x: Optional[np.ndarray] = None
    y: Optional[np.ndarray] = None
    name: Optional[np.ndarray] = None
    attrs: Dict[str, np.ndarray] = field(default_factory=dict)
    polygons: List[tuple] = field(default_factory=list)   # 本版本：轴对齐矩形
    nodes: Optional[np.ndarray] = None                    # (n, 2) 路网节点
    edges: Optional[np.ndarray] = None                    # (m, 5) u, v, length, speed, oneway
    value: Optional[np.ndarray] = None                    # 栅格
    transform: Optional[tuple] = None

    def kind(self) -> str:
        return self.layer_type

@dataclass
class Dataset:
    """一次运行的全部输入。"""

    grid: Grid
    units: UnitTable
    obs: ObsTable
    layers: Dict[str, LayerData]
    crs: str
    project_name: str
    # 单元级属性（规划 / 建筑类字段，供 attribute 算子直接读取）
    unit_attrs: Dict[str, np.ndarray] = field(default_factory=dict)
    # 因子结果：code -> (n_units,) 数组
    attrs: Dict[str, np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.attrs = {}

    @property
    def n_units(self) -> int:
        return len(self.units)

    def layer(self, layer_id: str) -> LayerData:
        if layer_id not in self.layers:
            raise KeyError("未注册的图层：%s" % layer_id)
        return self.layers[layer_id]

    def n_obs(self) -> int:
        return len(self.obs)

    def design_matrix(self, codes: List[str]) -> np.ndarray:
        """按因子编码顺序取列，缺失即报错（不允许静默补 0）。"""
        missing = [c for c in codes if c not in self.attrs]
        if missing:
            raise KeyError("以下因子尚未计算：%s" % ", ".join(missing))
        return np.column_stack([self.attrs[c] for c in codes])
