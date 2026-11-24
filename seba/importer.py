# -*- coding: utf-8 -*-
"""CSV 导入：列映射、坐标处理、构建内部数据契约。

不依赖 geopandas / shapely：
  · 坐标：支持投影坐标（x / y）或经纬度（自动换算为研究区局部平面坐标）
  · 几何：评估单元按"方格"处理（边长由用户指定），面要素用外接矩形
  · 路网：边清单（起止点坐标 + 等级 + 单向），节点按坐标去重
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .datamodel import Dataset, Grid, LayerData, ObsTable, UnitTable

__all__ = ["ImportError2", "read_bytes", "parse_table", "guess_map", "build_dataset"]


class ImportError2(ValueError):
    """导入过程中的可读错误。"""


# 读文件

def read_bytes(b64: str) -> str:
    raw = base64.b64decode(b64.split(",")[-1])
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_table(text: str) -> pd.DataFrame:
    head = text.splitlines()[0] if text.strip() else ""
    sep = "\t" if head.count("\t") > head.count(",") else ("," if "," in head else r"\s+")
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    if not len(df.columns):
        raise ImportError2("文件里没有识别到表头，请确认是 CSV 或 TSV")
    return df


# 列映射猜测

_KEYS = {
    "id": ["单元编号", "单元id", "单元id", "编号", "宗地号", "小区", "unit_id", "id", "code"],
    "lon": ["经度", "lon", "lng", "longitude"],
    "lat": ["纬度", "lat", "latitude"],
    "x": ["x坐标", "横坐标", "东坐标", "x", "easting"],
    "y": ["y坐标", "纵坐标", "北坐标", "y", "northing"],
    "price": ["成交总价", "总价", "成交价", "价格", "price", "amount"],
    "unit_price": ["成交单价", "单价", "均价", "元/㎡", "元/m2", "unit_price"],
    "date": ["成交日期", "成交时间", "日期", "时间", "date", "deal_date"],
    "admin": ["行政区", "区县", "街道", "admin"],
    "population": ["人口", "常住人口", "户数", "population"],
    "weight": ["权重", "供给量", "规模", "床位数", "班数", "capacity", "weight"],
    "kind": ["类型", "类别", "kind", "type"],
    "fx": ["起点x", "from_x", "起x", "起点经度"],
    "fy": ["起点y", "from_y", "起y", "起点纬度"],
    "tx": ["终点x", "to_x", "终x", "终点经度"],
    "ty": ["终点y", "to_y", "终y", "终点纬度"],
    "cls": ["等级", "道路等级", "class"],
    "oneway": ["单向", "oneway"],
}


def _find(cols: List[str], keys: List[str]) -> Optional[str]:
    low = {c: c.lower().replace(" ", "") for c in cols}
    for k in keys:
        kl = k.lower()
        for c in cols:
            if low[c] == kl:
                return c
    for k in keys:
        kl = k.lower()
        for c in cols:
            if kl in low[c]:
                return c
    return None


def guess_map(cols: List[str], kind: str) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    if kind == "units":
        out["id"] = _find(cols, _KEYS["id"])
        out["lon"] = _find(cols, _KEYS["lon"])
        out["lat"] = _find(cols, _KEYS["lat"])
        out["x"] = _find(cols, ["x坐标", "横坐标", "东坐标", "easting"]) or _find(cols, ["x"])
        out["y"] = _find(cols, ["y坐标", "纵坐标", "北坐标", "northing"]) or _find(cols, ["y"])
        out["admin"] = _find(cols, _KEYS["admin"])
        out["population"] = _find(cols, _KEYS["population"])
    elif kind == "obs":
        out["unit_id"] = _find(cols, _KEYS["id"])
        out["price"] = _find(cols, _KEYS["price"])
        out["unit_price"] = _find(cols, _KEYS["unit_price"])
        out["date"] = _find(cols, _KEYS["date"])
    elif kind == "point":
        out["x"] = out["lon"] = _find(cols, _KEYS["lon"])
        out["y"] = out["lat"] = _find(cols, _KEYS["lat"])
        if not out["x"]:
            out["x"] = _find(cols, ["x坐标", "横坐标", "easting"]) or _find(cols, ["x"])
            out["y"] = _find(cols, ["y坐标", "纵坐标", "northing"]) or _find(cols, ["y"])
        out["weight"] = _find(cols, _KEYS["weight"])
    elif kind == "network":
        out["fx"] = _find(cols, _KEYS["fx"])
        out["fy"] = _find(cols, _KEYS["fy"])
        out["tx"] = _find(cols, _KEYS["tx"])
        out["ty"] = _find(cols, _KEYS["ty"])
        out["cls"] = _find(cols, _KEYS["cls"])
        out["oneway"] = _find(cols, _KEYS["oneway"])
    return out


# 坐标

def _to_xy(df: pd.DataFrame, m: Dict, what: str) -> Tuple[np.ndarray, np.ndarray, str]:
    def col(k):
        c = m.get(k)
        if not c or c not in df.columns:
            return None
        return pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)

    x, y = col("x"), col("y")
    lon, lat = col("lon"), col("lat")
    if x is not None and y is not None:
        note = "投影坐标（米）"
    elif lon is not None and lat is not None:
        lat0 = float(np.nanmean(lat))
        x = lon * 111320.0 * math.cos(math.radians(lat0))
        y = lat * 110540.0
        note = "经纬度 → 已换算为研究区局部平面坐标（中心纬度 %.3f°）" % lat0
    else:
        raise ImportError2("%s 缺少坐标列：请指定“经度/纬度”或“X/Y”两列" % what)

    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        raise ImportError2("%s 里有效坐标少于 3 条，无法建模" % what)
    if (~ok).sum():
        df.drop(df.index[~ok], inplace=True)
    x = x[ok] - np.nanmin(x[ok])
    y = y[ok] - np.nanmin(y[ok])
    return x, y, note


def _text(item: Dict) -> str:
    """导入项既可能直接带文本，也可能带 base64 原文。"""
    txt = (item or {}).get("text")
    if txt:
        return txt
    b64 = (item or {}).get("b64")
    if b64:
        return read_bytes(b64)
    raise ImportError2("缺少文件内容")


# 构建

def _auto_network(x0: float, y0: float, x1: float, y1: float, cell: float) -> np.ndarray:
    """没有提供路网时，按研究区范围生成规则格网示意路网。"""
    nx = max(2, int(math.ceil((x1 - x0) / cell)) + 1)
    ny = max(2, int(math.ceil((y1 - y0) / cell)) + 1)
    idx = lambda i, j: j * nx + i  # noqa: E731
    edges = []
    for j in range(ny):
        for i in range(nx - 1):
            cls = 1 if j % 5 == 0 else (2 if j % 2 == 0 else 3)
            edges.append((idx(i, j), idx(i + 1, j), cell, cls, 0))
    for i in range(nx):
        for j in range(ny - 1):
            cls = 1 if i % 5 == 0 else (2 if i % 2 == 0 else 3)
            edges.append((idx(i, j), idx(i, j + 1), cell, cls, 0))
    return np.array(edges, dtype=float), nx * ny, (x0, y0, x1, y1, nx, ny)


def build_dataset(spec: Dict, project_name: str = "我的工程") -> Tuple[Dataset, List[str]]:
    """按导入规格构建 Dataset。返回 (数据集, 提示信息列表)。"""
    notes: List[str] = []
    cell = float(spec.get("cell_m") or 250.0)
    if cell <= 0:
        raise ImportError2("单元尺寸必须大于 0")

    # 评估单元
    u = spec.get("units") or {}
    if not (u.get("text") or u.get("b64")):
        raise ImportError2("请先导入“评估单元”文件")
    udf = parse_table(_text(u))
    umap = u.get("map") or guess_map(list(udf.columns), "units")
    ux, uy, note = _to_xy(udf, umap, "评估单元")
    notes.append("评估单元：" + note)

    n = len(udf)
    id_col = umap.get("id")
    if id_col and id_col in udf.columns:
        unit_id = udf[id_col].astype(str).to_numpy()
    else:
        unit_id = np.array(["U%05d" % (i + 1) for i in range(n)])
        notes.append("评估单元：未指定编号列，已按行号生成 U00001…")

    adm_col = umap.get("admin")
    admin = udf[adm_col].astype(str).to_numpy() if adm_col and adm_col in udf.columns \
        else np.array(["未分区"] * n)
    pop_col = umap.get("population")
    pop = pd.to_numeric(udf[pop_col], errors="coerce").fillna(0).to_numpy(dtype=float) \
        if pop_col and pop_col in udf.columns else np.zeros(n)

    x0, x1 = 0.0, float(ux.max() + cell)
    y0, y1 = 0.0, float(uy.max() + cell)
    grid = Grid(nx=max(1, int(math.ceil((x1 - x0) / cell))),
                ny=max(1, int(math.ceil((y1 - y0) / cell))),
                cell=cell, x0=x0, y0=y0)

    units = UnitTable(
        unit_id=unit_id,
        ix=np.clip((ux // cell).astype(int), 0, grid.nx - 1),
        iy=np.clip((uy // cell).astype(int), 0, grid.ny - 1),
        x=ux, y=uy,
        area=np.full(n, cell * cell, dtype=float),
        admin_code=admin,
        use_type=np.array(["未分类"] * n),
        population=pop,
        asof_date=str(spec.get("asof_date") or "—"),
    )

    # 单元属性（供"属性直读"类因子使用）
    unit_attrs: Dict[str, np.ndarray] = {}
    for extra in (u.get("attrs") or []):
        col = extra.get("col")
        if col and col in udf.columns:
            vals = pd.to_numeric(udf[col], errors="coerce")
            if vals.notna().sum() < len(vals) * 0.5:
                continue
            unit_attrs[extra.get("key") or col] = vals.fillna(vals.median()).to_numpy(dtype=float)
    if unit_attrs:
        notes.append("评估单元：已读取 %d 个属性字段（%s）" % (len(unit_attrs), "、".join(unit_attrs)))

    # 成交
    o = spec.get("obs") or {}
    if not (o.get("text") or o.get("b64")):
        raise ImportError2("请导入“成交记录”文件")
    odf = parse_table(_text(o))
    omap = o.get("map") or guess_map(list(odf.columns), "obs")
    idc = omap.get("unit_id")
    if not idc or idc not in odf.columns:
        raise ImportError2("成交记录缺少“单元编号”列，无法与评估单元对应")
    idx_map = {uid: i for i, uid in enumerate(unit_id)}
    keep, rows = [], []
    for k, rid in enumerate(odf[idc].astype(str).to_numpy()):
        if rid in idx_map:
            keep.append(idx_map[rid])
            rows.append(k)
    if not keep:
        raise ImportError2("成交记录里的单元编号与评估单元表完全对不上，请检查两表编号写法是否一致")
    odf = odf.iloc[rows].reset_index(drop=True)
    keep = np.array(keep, dtype=int)

    up_col, p_col = omap.get("unit_price"), omap.get("price")
    if up_col and up_col in odf.columns:
        price_pm2 = pd.to_numeric(odf[up_col], errors="coerce").to_numpy(dtype=float)
        notes.append("成交：直接使用“成交单价”列")
    elif p_col and p_col in odf.columns:
        total = pd.to_numeric(odf[p_col], errors="coerce").to_numpy(dtype=float)
        avg_area = float(spec.get("avg_area_m2") or 90.0)
        price_pm2 = total / max(avg_area, 1.0)
        notes.append("成交：由“成交总价”除以套均面积 %.0f ㎡ 换算单价" % avg_area)
    else:
        raise ImportError2("成交记录需要“成交单价”或“成交总价”列")

    dcol = omap.get("date")
    dates = odf[dcol].astype(str).to_numpy() if dcol and dcol in odf.columns \
        else np.array(["—"] * len(odf))

    ok = np.isfinite(price_pm2) & (price_pm2 > 0)
    obs = ObsTable(
        unit_idx=keep[ok],
        price=price_pm2[ok] * float(spec.get("avg_area_m2") or 90.0),
        unit_price=price_pm2[ok],
        deal_date=dates[ok],
        price_type=np.array(["deal"] * int(ok.sum())),
        source=np.array(["user"] * int(ok.sum())),
        weight=np.ones(int(ok.sum()), dtype=float),
    )
    if ok.sum() < 30:
        notes.append("⚠ 有效成交只有 %d 条，回归结果不稳定，建议补到 100 条以上" % ok.sum())

    # 路网
    nw = spec.get("network") or {}
    if nw.get("text") or nw.get("b64"):
        ndf = parse_table(_text(nw))
        nmap = nw.get("map") or guess_map(list(ndf.columns), "network")
        need = ["fx", "fy", "tx", "ty"]
        miss = [k for k in need if not nmap.get(k)]
        if miss:
            raise ImportError2("路网文件缺少列：起点X/Y、终点X/Y 未能识别")
        coords_to_xy = {}
        for k in need:
            coords_to_xy[k] = pd.to_numeric(ndf[nmap[k]], errors="coerce").to_numpy(dtype=float)
        raw_all = np.concatenate([coords_to_xy[k] for k in need])
        lonlat = bool(np.nanmax(np.abs(raw_all)) <= 180.0)
        xs = np.concatenate([coords_to_xy["fx"], coords_to_xy["tx"]])
        ys = np.concatenate([coords_to_xy["fy"], coords_to_xy["ty"]])
        if lonlat:
            lat0 = float(np.nanmean(ys))
            coords_to_xy["fx"] = coords_to_xy["fx"] * 111320.0 * math.cos(math.radians(lat0))
            coords_to_xy["tx"] = coords_to_xy["tx"] * 111320.0 * math.cos(math.radians(lat0))
            coords_to_xy["fy"] = coords_to_xy["fy"] * 110540.0
            coords_to_xy["ty"] = coords_to_xy["ty"] * 110540.0
            notes.append("路网：按经纬度换算为局部平面坐标")
        minx = min(np.nanmin(coords_to_xy["fx"]), np.nanmin(coords_to_xy["tx"]))
        miny = min(np.nanmin(coords_to_xy["fy"]), np.nanmin(coords_to_xy["ty"]))
        coords_to_xy = {k: v - (minx if k in ("fx", "tx") else miny) for k, v in coords_to_xy.items()}

        key = {}
        nxy = []
        edges = []
        cls_arr = pd.to_numeric(ndf[nmap["cls"]], errors="coerce").fillna(3).to_numpy() \
            if nmap.get("cls") else np.full(len(ndf), 3)
        ow_arr = (pd.to_numeric(ndf[nmap["oneway"]], errors="coerce").fillna(0).to_numpy() > 0) \
            if nmap.get("oneway") else np.zeros(len(ndf), dtype=bool)

        def nid(px, py):
            kk = (round(px * 2) / 2, round(py * 2) / 2)
            if kk not in key:
                key[kk] = len(nxy)
                nxy.append(kk)
            return key[kk]

        for i in range(len(ndf)):
            a = (coords_to_xy["fx"][i], coords_to_xy["fy"][i])
            b = (coords_to_xy["tx"][i], coords_to_xy["ty"][i])
            if not all(np.isfinite(v) for v in (*a, *b)):
                continue
            u_, v_ = nid(*a), nid(*b)
            L = math.hypot(a[0] - b[0], a[1] - b[1])
            if L <= 0:
                continue
            edges.append((u_, v_, L, int(cls_arr[i]), 1 if ow_arr[i] else 0))
        if len(edges) < 10:
            raise ImportError2("路网有效边过少（%d 条），请检查起止点坐标列" % len(edges))
        net = LayerData(
            layer_id="road_net", layer_type="network", crs="用户导入", asof_date=str(spec.get("asof_date") or "—"),
            version="u1", fields=["length", "speed_class", "oneway"],
            nodes=np.array(nxy, dtype=float), edges=np.array(edges, dtype=float),
        )
        notes.append("路网：%d 个节点 / %d 条边" % (len(nxy), len(edges)))
    else:
        edges, nn, (a0, b0, a1, b1, gnx, gny) = _auto_network(
            x0, y0, x0 + grid.nx * cell, y0 + grid.ny * cell, cell
        )
        net = LayerData(
            layer_id="road_net", layer_type="network", crs="自动生成", asof_date="—", version="auto1",
            fields=["length", "speed_class", "oneway"],
            nodes=np.array([((k % gnx) * cell, (k // gnx) * cell) for k in range(nn)], dtype=float),
            edges=edges,
        )
        notes.append("⚠ 未导入路网，已按格网自动生成示意路网；路网类因子仅作演示，请勿用于正式评估")

    layers: Dict[str, LayerData] = {"road_net": net}

    # 点 / 面图层
    for i, ly in enumerate(spec.get("layers") or []):
        if not (ly.get("text") or ly.get("b64")):
            continue
        ldf = parse_table(_text(ly))
        lmap = ly.get("map") or guess_map(list(ldf.columns), "point")
        kind = (ly.get("kind") or "point").lower()
        lid = ly.get("id") or ("layer_%d" % (i + 1))
        name = ly.get("name") or lmap.get("name") or lid
        if kind == "polygon":
            raise ImportError2("面图层暂只支持内置演示数据，请先用点图层导入（如公园中心点）")
        lx, lyy, lnote = _to_xy(ldf, lmap, "图层“%s”" % name)
        attrs = {}
        if lmap.get("weight") and lmap["weight"] in ldf.columns:
            w = pd.to_numeric(ldf[lmap["weight"]], errors="coerce")
            attrs["weight"] = w.fillna(w.median()).to_numpy(dtype=float)
        layers[lid] = LayerData(
            layer_id=lid, layer_type="point", crs="用户导入",
            asof_date=str(spec.get("asof_date") or "—"), version="u1",
            fields=list(attrs), x=lx, y=lyy, attrs=attrs,
            aux_meta={"display_name": name},
        )
        notes.append("图层“%s”：%d 个点%s" % (name, len(lx), "，含权重字段" if attrs else ""))

    ds = Dataset(
        grid=grid, units=units, obs=obs, layers=layers,
        crs="用户导入（局部平面坐标，米）",
        project_name=project_name,
        unit_attrs=unit_attrs,
    )
    return ds, notes
