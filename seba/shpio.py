# -*- coding: utf-8 -*-
"""纯 Python 读取 Shapefile（点 / 线 / 面 + DBF 属性），不依赖 geopandas。

只实现本工程需要的部分：
  · ShapeType 1  Point / 5 Polygon / 3 Polyline / 8 MultiPoint
  · DBF 属性表（UTF-8 与 GBK 自动识别）
  · 读取 .prj 判断地理坐标还是投影坐标

坐标系不做重投影，只提供本地等距圆柱近似（适合市域尺度）。
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

__all__ = ["Shapefile", "read_shapefile", "dbf_field_names"]

_TYPE = {1: "point", 3: "polyline", 5: "polygon", 8: "multipoint", 11: "point", 13: "polyline", 15: "polygon"}


@dataclass
class Shapefile:
    path: str
    kind: str                       # point / polyline / polygon
    geoms: list = field(default_factory=list)     # 每要素：ndarray(n,2) 或 ndarray(m,n,2)
    attrs: Dict[str, List[str]] = field(default_factory=dict)
    prj: str = ""
    n: int = 0

    @property
    def geographic(self) -> bool:
        p = (self.prj or "").upper()
        return "GEOGCS" in p or "GEOGRAPHIC" in p

    def field(self, name: str) -> List[str]:
        if name not in self.attrs:
            raise KeyError("字段不存在：%s（可用：%s）" % (name, ", ".join(self.attrs)))
        return self.attrs[name]

    def to_lonlat(self) -> None:
        """若为投影坐标则原样返回；本工具只做地理→平面的换算，不反向。"""
        return None


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def dbf_field_names(path: str) -> List[str]:
    out = []
    with open(path, "rb") as f:
        f.read(32)
        while True:
            fd = f.read(32)
            if not fd or fd[0:1] == b"\r":
                break
            out.append(_decode(fd[0:11]).split("\x00")[0].strip())
    return out


def _read_dbf(path: str) -> Dict[str, List[str]]:
    with open(path, "rb") as f:
        head = f.read(32)
        nrec, hlen, rlen = struct.unpack("<IHH", head[4:12])
        fields, off = [], 1
        while True:
            fd = f.read(32)
            if not fd or fd[0:1] == b"\r":
                break
            name = _decode(fd[0:11]).split("\x00")[0].strip()
            fields.append((name, off, fd[16]))
            off += fd[16]
        f.seek(hlen)
        out = {n: [] for n, _, _ in fields}
        for _ in range(nrec):
            rec = f.read(rlen)
            if len(rec) < rlen:
                break
            for n, o, ln in fields:
                out[n].append(_decode(rec[o:o + ln]).strip())
    return out


def _prj(path: str) -> str:
    p = os.path.splitext(path)[0] + ".prj"
    if not os.path.exists(p):
        return ""
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""


def read_shapefile(path: str, limit: Optional[int] = None) -> Shapefile:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    geoms: list = []
    kind = ""
    with open(path, "rb") as f:
        head = f.read(100)
        if len(head) < 100 or struct.unpack(">i", head[0:4])[0] != 9994:
            raise ValueError("不是标准 shapefile：%s" % path)
        stype = struct.unpack("<i", head[32:36])[0]
        kind = _TYPE.get(stype, "unknown")
        f.seek(100)
        while True:
            bh = f.read(8)
            if len(bh) < 8:
                break
            clen = struct.unpack(">i", bh[4:8])[0] * 2
            body = f.read(clen)
            if len(body) < clen:
                break
            st = struct.unpack("<i", body[0:4])[0]
            if st == 0:
                geoms.append(None)
                continue
            if st in (1, 11, 21):
                geoms.append(np.frombuffer(body[4:20], dtype="<f8").reshape(1, 2))
            elif st in (8, 18, 28):
                nb = struct.unpack("<i", body[36:40])[0]
                geoms.append(np.frombuffer(body[40:40 + 16 * nb], dtype="<f8").reshape(nb, 2))
            elif st in (3, 13, 23, 5, 15, 25):
                nparts = struct.unpack("<i", body[36:40])[0]
                npoints = struct.unpack("<i", body[40:44])[0]
                parts = np.frombuffer(body[44:44 + 4 * nparts], dtype="<i4")
                pts = np.frombuffer(body[44 + 4 * nparts:44 + 4 * nparts + 16 * npoints],
                                    dtype="<f8").reshape(npoints, 2)
                bounds = list(parts) + [npoints]
                rings = [pts[bounds[k]:bounds[k + 1]] for k in range(nparts)]
                geoms.append(rings if kind == "polygon" else
                             (rings[0] if nparts == 1 else np.vstack(rings)))
            else:
                geoms.append(None)
            if limit and len(geoms) >= limit:
                break

    dbf = os.path.splitext(path)[0] + ".dbf"
    attrs = _read_dbf(dbf) if os.path.exists(dbf) else {}
    # 属性行数可能与几何行数不完全一致（损坏文件），截齐
    n = len(geoms)
    for k in list(attrs):
        if len(attrs[k]) < n:
            attrs[k] = attrs[k] + [""] * (n - len(attrs[k]))
        elif len(attrs[k]) > n:
            attrs[k] = attrs[k][:n]
    return Shapefile(path=path, kind=kind, geoms=geoms, attrs=attrs, prj=_prj(path), n=n)


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------

def ring_area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def polygon_area(rings: List[np.ndarray]) -> float:
    """外环面积取正，内环（洞）按带符号面积扣除。"""
    if not rings:
        return 0.0
    a = abs(ring_area(rings[0]))
    for r in rings[1:]:
        a -= abs(ring_area(r))
    return max(a, 0.0)


def polygon_centroid(rings: List[np.ndarray]) -> Tuple[float, float]:
    """按面积加权的质心；退化时退回顶点均值。"""
    if not rings:
        return (float("nan"), float("nan"))
    r = rings[0]
    x, y = r[:, 0], r[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    a = cross.sum() / 2.0
    if abs(a) < 1e-12:
        return (float(x.mean()), float(y.mean()))
    cx = ((x + np.roll(x, -1)) * cross).sum() / (6.0 * a)
    cy = ((y + np.roll(y, -1)) * cross).sum() / (6.0 * a)
    return (float(cx), float(cy))


def to_local_xy(lon: np.ndarray, lat: np.ndarray, lat0: Optional[float] = None):
    """经纬度 → 局部平面坐标（米）。市域尺度足够，误差 < 0.1%。"""
    lat0 = float(np.mean(lat)) if lat0 is None else lat0
    kx = 111320.0 * np.cos(np.radians(lat0))
    ky = 110540.0
    return (lon - np.min(lon)) * kx, (lat - np.min(lat)) * ky


def points_in_rings(px: np.ndarray, py: np.ndarray, rings: List[np.ndarray]) -> np.ndarray:
    """射线法判断点是否落在多边形内（含洞）。"""
    inside = np.zeros(px.size, dtype=bool)
    for idx, ring in enumerate(rings):
        n = ring.shape[0]
        if n < 3:
            continue
        x1, y1 = ring[:, 0], ring[:, 1]
        x0 = px.copy()
        res = np.zeros(px.size, dtype=bool)
        for k in range(n - 1):
            ax, ay = x1[k], y1[k]
            bx, by = x1[k + 1], y1[k + 1]
            cond = ((ay > py) != (by > py))
            if not cond.any():
                continue
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (bx - ax) * (py - ay) / np.where(by != ay, by - ay, 1e-12) + ax
            res ^= cond & (px < xint)
        inside = res if idx == 0 else (inside & ~res)
    return inside
