# -*- coding: utf-8 -*-
"""统一的矢量/表格读取入口。

支持 .shp / .geojson / .kml / .gdb / .csv / .xlsx，全部归一成 shpio.Shapefile
结构（geoms + attrs + kind + prj），这样下游 realdata 完全不用改。

约定：
  - 面要素：geoms[i] 是环列表[ndarray(n,2), ...]
  - 线/点要素：geoms[i] 是 ndarray(n,2)（多段时取最长的一段，保证属性与几何一一对应）
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .shpio import Shapefile, read_shapefile

__all__ = ["read_vector", "read_table", "vector_exts", "table_exts"]

vector_exts = (".shp", ".geojson", ".json", ".kml")
table_exts = (".csv", ".txt", ".xlsx", ".xls")

def _empty(path: str, kind: str = "polygon") -> Shapefile:
    return Shapefile(path=path, kind=kind, geoms=[], attrs={}, prj="", n=0)

# GeoJSON

def _from_geojson(path: str) -> Shapefile:
    with open(path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)
    feats = gj.get("features", []) if isinstance(gj, dict) else list(gj or [])
    if not feats:
        return _empty(path)

    kinds: List[str] = []
    geoms: List[Any] = []
    cols: Dict[str, List[str]] = {}

    def push(props):
        for k in props:
            if k not in cols:
                cols[k] = [""] * (len(geoms) - 1)
        for k in cols:
            v = props.get(k, "")
            cols[k].append("" if v is None else str(v))

    for ft in feats:
        g = ft.get("geometry") or {}
        t = g.get("type") or ""
        co = g.get("coordinates")
        props = ft.get("properties") or {}
        if not co:
            continue
        if t == "Polygon":
            rings = [np.asarray(r, dtype=float)[:, :2] for r in co if len(r) >= 3]
            if not rings:
                continue
            kinds.append("polygon")
            geoms.append(rings)
            push(props)
        elif t == "MultiPolygon":
            rings = []
            for poly in co:
                for r in poly:
                    if len(r) >= 3:
                        rings.append(np.asarray(r, dtype=float)[:, :2])
            if not rings:
                continue
            kinds.append("polygon")
            geoms.append(rings)
            push(props)
        elif t in ("LineString", "MultiLineString"):
            parts = [np.asarray(co, dtype=float)[:, :2]] if t == "LineString" else \
                    [np.asarray(p, dtype=float)[:, :2] for p in co if len(p) >= 2]
            parts = [p for p in parts if p.shape[0] >= 2]
            if not parts:
                continue
            best = max(parts, key=lambda a: a.shape[0])
            kinds.append("polyline")
            geoms.append(best)
            push(props)
        elif t in ("Point", "MultiPoint"):
            arr = np.asarray(co if t == "Point" else co[0], dtype=float).reshape(1, 2)
            kinds.append("point")
            geoms.append(arr)
            push(props)

    kind = "polygon" if kinds.count("polygon") >= max(1, len(kinds) // 2) else (
        "polyline" if "polyline" in kinds else "point")
    return Shapefile(path=path, kind=kind, geoms=geoms, attrs=cols,
                     prj="GEOGCS[\"WGS 84\"]", n=len(geoms))

# KML

def _kml_coords(text: str) -> np.ndarray:
    pts = []
    for tok in (text or "").replace("\n", " ").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return np.asarray(pts, dtype=float) if pts else np.zeros((0, 2))

def _from_kml(path: str) -> Shapefile:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    def tag(n):
        return ns + n

    geoms: List[Any] = []
    cols: Dict[str, List[str]] = {}
    kinds: List[str] = []

    for pm in root.iter(tag("Placemark")):
        props: Dict[str, str] = {}
        for d in pm.iter(tag("Data")):
            props[d.get("name") or ""] = (d.findtext(tag("value")) or "").strip()
        nm = pm.findtext(tag("name"))
        if nm:
            props.setdefault("name", nm.strip())

        poly = pm.find(".//" + tag("Polygon"))
        line = pm.find(".//" + tag("LineString"))
        pt = pm.find(".//" + tag("Point"))

        geom = None
        if poly is not None:
            rings = []
            outer = poly.find(tag("outerBoundaryIs"))
            if outer is not None:
                c = _kml_coords(outer.findtext(".//" + tag("coordinates")))
                if c.shape[0] >= 3:
                    rings.append(c)
            for inner in poly.findall(tag("innerBoundaryIs")):
                c = _kml_coords(inner.findtext(".//" + tag("coordinates")))
                if c.shape[0] >= 3:
                    rings.append(c)
            if rings:
                geom = rings
                kinds.append("polygon")
        elif line is not None:
            c = _kml_coords(line.findtext(".//" + tag("coordinates")))
            if c.shape[0] >= 2:
                geom = c
                kinds.append("polyline")
        elif pt is not None:
            c = _kml_coords(pt.findtext(".//" + tag("coordinates")))
            if c.shape[0] >= 1:
                geom = c[:1]
                kinds.append("point")
        if geom is None:
            continue

        for k in props:
            if k not in cols:
                cols[k] = [""] * (len(geoms))
        for k in cols:
            cols[k].append(props.get(k, ""))
        geoms.append(geom)

    kind = "polygon" if kinds.count("polygon") >= max(1, len(kinds) // 2) else (
        "polyline" if "polyline" in kinds else "point")
    return Shapefile(path=path, kind=kind, geoms=geoms, attrs=cols, prj="GEOGCS[\"WGS 84\"]",
                     n=len(geoms))

# FileGDB（需要 pyogrio + shapely，均为可选依赖）

def gdb_layers(path: str) -> List[Tuple[str, str, int]]:
    """列出 gdb 里的图层：[(name, geometry_type, n_features), ...]"""
    try:
        import pyogrio
    except Exception:
        return []
    out = []
    try:
        for name, gt in pyogrio.list_layers(path):
            try:
                info = pyogrio.read_info(path, layer=str(name))
                n = int(info.get("features") or 0)
            except Exception:
                n = 0
            out.append((str(name), str(gt), n))
    except Exception:
        return []
    return out

def _from_gdb(path: str, layer: Optional[str] = None) -> Shapefile:
    from pyogrio.raw import read as _read
    from shapely import wkb as _wkb

    layers = gdb_layers(path)
    if not layers:
        return _empty(path)
    if layer is None:
        layer = max(layers, key=lambda t: t[2])[0]

    meta, fids, gbuf, fields = _read(path, layer=layer)
    names = [str(x) for x in meta["fields"]]
    attrs: Dict[str, List[str]] = {n: [] for n in names}
    geoms: List[Any] = []
    kinds: List[str] = []

    for i, wb in enumerate(gbuf):
        try:
            g = _wkb.loads(bytes(wb))
        except Exception:
            continue
        gt = g.geom_type
        if gt in ("Polygon", "MultiPolygon"):
            polys = [g] if gt == "Polygon" else list(g.geoms)
            rings = []
            for p in polys:
                rings.append(np.asarray(p.exterior.coords, dtype=float)[:, :2])
                for hole in p.interiors:
                    rings.append(np.asarray(hole.coords, dtype=float)[:, :2])
            if not rings:
                continue
            geom, k = rings, "polygon"
        elif gt in ("LineString", "MultiLineString"):
            parts = [g] if gt == "LineString" else list(g.geoms)
            parts = [np.asarray(p.coords, dtype=float)[:, :2] for p in parts]
            parts = [p for p in parts if p.shape[0] >= 2]
            if not parts:
                continue
            geom, k = max(parts, key=lambda a: a.shape[0]), "polyline"
        elif gt in ("Point", "MultiPoint"):
            p = g if gt == "Point" else list(g.geoms)[0]
            geom, k = np.asarray([[p.x, p.y]], dtype=float), "point"
        else:
            continue
        geoms.append(geom)
        kinds.append(k)
        for n in names:
            v = fields[names.index(n)][i]
            attrs[n].append("" if v is None else str(v))

    kind = "polygon" if kinds.count("polygon") >= max(1, len(kinds) // 2) else (
        "polyline" if "polyline" in kinds else "point")
    return Shapefile(path=path, kind=kind, geoms=geoms, attrs=attrs,
                     prj="GEOGCS[\"WGS 84\"]", n=len(geoms))

# 统一入口

def read_vector(path: str, layer: Optional[str] = None) -> Shapefile:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".shp":
        return read_shapefile(path)
    if ext in (".geojson", ".json"):
        return _from_geojson(path)
    if ext == ".kml":
        return _from_kml(path)
    if ext == ".gdb" or path.lower().endswith(".gdb"):
        return _from_gdb(path, layer)
    raise ValueError("不支持的矢量格式：%s" % ext)

def read_table(path: str, sheet: Optional[str] = None) -> Tuple[List[str], List[List[str]]]:
    """读取表格：返回 (列名, 数据行)。csv/txt 与 xlsx/xls 都走这里。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        try:
            from openpyxl import load_workbook
        except Exception as exc:
            raise ValueError("读取 Excel 需要 openpyxl：%s" % exc)
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb[wb.sheetnames[0]]
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(["" if v is None else str(v) for v in r])
        wb.close()
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            return [], []
        return rows[0], rows[1:]

    raw = open(path, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    text = text or raw.decode("latin-1", errors="ignore")
    import csv as _csv
    import io

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []
    delim = ","
    for d in (",", ";", "\t", "|"):
        if lines[0].count(d) >= max(1, len(lines[0]) // 40):
            delim = d
            break
    rows = list(_csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    return [c.strip() for c in rows[0]], [[c.strip() for c in r] for r in rows[1:]]
