# -*- coding: utf-8 -*-
"""真实地理数据装配：上海村界 + 真实路网 + 土地利用 -> 评估单元与因子。

不依赖 geopandas / shapely / rasterio，几何运算全部用 numpy 实现。

关键处理（真实数据必须做，否则结果不可信）：
  1. 路网拓扑清洗：OSM 路段端点常有米级偏差，必须按容差合并成拓扑网络，否则是几千个孤岛
  2. 只保留最大连通分量参与可达性计算
  3. 土地利用栅格化：把面状地类栅格到 100 m 网格，再用圆盘邻域聚合出单元级绿地率 / 水面率
  4. 道路密度：按网格累计路段长度（km/km²）
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .datamodel import Dataset, Grid, LayerData, ObsTable, UnitTable
from .net import CSRGraph
from .shpio import Shapefile, points_in_rings, polygon_area, polygon_centroid
from .vec import read_vector

__all__ = ["RealDataError", "DATA_ROOT", "DISTRICT_PRICE",
           "list_districts", "build_district_dataset"]

def _resolve_data_root() -> str:
    """数据根目录：环境变量 > 本地镜像 > 原始位置。

    本地镜像用于摆脱移动硬盘依赖-把用到的几份数据按相同相对路径
    拷到本地盘即可，代码无需改动。
    """
    cands = [
        os.environ.get("SEBA_DATA_ROOT"),
        r"D:\SEBA_数据",
        r"F:\上海师大\各种地理数据",
    ]
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return cands[-1]

DATA_ROOT = _resolve_data_root()

# 默认数据源（上海）。其他城市只需在同目录放一份 datasource.json 覆盖下面几项，
# 或在程序里调用 configure()。字段名同样可配，因为不同城市的 shapefile 列名不一致。
_DEFAULT_SOURCE = {
    "name": "上海",
    "village": os.path.join(DATA_ROOT, r"2024全国村级行政边界\1上海村社区界\上海村界.shp"),
    "roads": os.path.join(DATA_ROOT, r"2024年道路数据（全国、分省、分城市）\分城市的道路数据\【立方数据学社】上海市\上海市.shp"),
    "landuse": os.path.join(DATA_ROOT, r"2026省级土地利用\各省土地利用矢量2026shp\上海市土地利用2026.shp"),
    "poi_gdb": os.path.join(DATA_ROOT, r"OSM_2014_2025\osm中国分省20260922\osm_china_gdb_zip\上海.gdb.zip"),
    # 字段名映射：不同城市的 shp 列名不同，这里统一声明
    "fields": {
        "village_district": "所属区e",
        "village_street": "所属街e",
        "village_name": "居委名",
        "road_class": "fclass",
        "road_oneway": "oneway",
        "landuse_class": "fclass",
    },
    # 参考点（区级均价用于价格水平锚定，可换成目标城市的公开发布价）
    "price_by_district": {},
    "cbd": [121.4737, 31.2304],
}

SOURCE = dict(_DEFAULT_SOURCE)

def configure(**kw):
    """覆盖数据源配置（路径、字段、参考价）。"""
    for k, v in kw.items():
        if k == "fields":
            SOURCE["fields"] = {**SOURCE["fields"], **v}
        elif k == "price_by_district":
            SOURCE["price_by_district"] = dict(v)
        else:
            SOURCE[k] = v
    _reload_paths()
    return SOURCE

def load_datasource(path: str):
    """从 JSON 载入其他城市的数据源配置。"""
    import json

    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    return configure(**cfg)

def _reload_paths():
    global P_VILLAGE, P_ROADS, P_LANDUSE, GDB_ZIP, DISTRICT_PRICE, RAIL_EXCLUDE
    P_VILLAGE = SOURCE["village"]
    P_ROADS = SOURCE["roads"]
    P_LANDUSE = SOURCE["landuse"]
    GDB_ZIP = SOURCE["poi_gdb"]
    if SOURCE.get("price_by_district"):
        DISTRICT_PRICE = dict(SOURCE["price_by_district"])
    if SOURCE.get("rail_exclude"):
        RAIL_EXCLUDE = tuple(SOURCE["rail_exclude"])

P_VILLAGE = SOURCE["village"]
P_ROADS = SOURCE["roads"]
P_LANDUSE = SOURCE["landuse"]
GDB_ZIP = SOURCE["poi_gdb"]

# 同目录若存在 datasource.json，自动覆盖（便于换城市而不改代码）
_AUTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "datasource.json")
if os.path.exists(_AUTO):
    try:  # pragma: no cover
        import json as _json

        with open(_AUTO, "r", encoding="utf-8") as _fh:
            _cfg = _json.load(_fh)
        SOURCE.update({k: v for k, v in _cfg.items() if k != "fields"})
        if "fields" in _cfg:
            SOURCE["fields"] = {**SOURCE["fields"], **_cfg["fields"]}
        P_VILLAGE = SOURCE["village"]
        P_ROADS = SOURCE["roads"]
        P_LANDUSE = SOURCE["landuse"]
        GDB_ZIP = SOURCE["poi_gdb"]
    except Exception:
        pass

# 2024 年上海二手住宅网签均价（区级，公开口径，用于价格水平锚定）
# 来源：2024 年上海二手住宅成交报告 / 房天下城区成交榜单
DISTRICT_PRICE = {
    # 上海市分区二手住宅中位挂牌单价（元/㎡）
    # 数据来源：GitHub 公开数据集（链家/安居客挂房源快照，共 47,939 条，覆盖 16 区）
    # 说明：为挂牌价而非成交价；本系统仅用它作为估算价格的水平锚点，
    #       挂牌相对成交的固定溢价不影响回归系数（见实现方案相关论证）。
    "黄浦区": 89012.0, "徐汇区": 80835.0, "长宁区": 74092.0, "虹口区": 68270.0,
    "静安区": 68132.0, "杨浦区": 67984.0, "普陀区": 64116.0, "浦东新区": 60340.0,
    "闵行区": 58253.0, "宝山区": 48684.0, "松江区": 40814.0, "嘉定区": 39401.0,
    "青浦区": 36630.0, "奉贤区": 26966.0, "金山区": 18611.0, "崇明区": 17714.0,
}

# 土地利用分类：fclass -> 三分类
GREEN_CLS = {"park", "grass", "forest", "garden", "green", "wood", "绿地", "公园",
             "meadow", "scrub", "orchard", "vineyard", "allotments",
             "recreation_ground", "heath"}
WATER_CLS = {"water", "river", "lake", "pond", "reservoir", "湿地", "水域"}
BUILT_CLS = {"residential", "industrial", "commercial", "retail", "school",
             "hospital", "university", "railway", "construction", "居住区"}

GDB_ZIP = os.path.join(DATA_ROOT, r"OSM_2014_2025\osm中国分省20260922\osm_china_gdb_zip\上海.gdb.zip")

# 商业设施（OSM POI 分类）-> "商场多不多"
SHOP_CLS = {
    "mall", "marketplace", "department_store", "supermarket", "convenience",
    "clothes", "shoes", "bag", "jewelry", "sports", "toys", "books", "stationery",
    "electronics", "mobile_phone", "computer", "furniture", "hardware", "garden_centre",
    "cosmetics", "gift", "art", "photo", "music", "video", "beverages", "bakery",
    "butcher", "greengrocer", "florist", "optician", "chemist", "pharmacy",
}
# 排除火车站，剩下的 railway_station 当作轨道站（上海 OSM 里地铁站多以此分类）
RAIL_EXCLUDE = ("火车站", "虹桥站", "上海站", "上海南站", "上海西站", "南翔北站")

RES_MIN_SHARE = 0.30   # 居住用地占比低于此值且名称非居委时，判为非住宅单元

# 名称明显属于非住宅用途的关键词（公园、商业、学校、办公等）
# 地块单独列出：村界数据里有一批商业/工业地块（五）这类单元，
# 名称不含商业/工业以外的设施词，但显然是经营性用地，不能当住宅。
_NONRES_NAME = re.compile(
    "公园|学校|大学|中学|小学|幼儿园|医院|公司|集团|基地|广场|办事处|街道办|"
    "政府|车站|机场|市场|陵园|公墓|寺|庙|产业园|工业园|园区|商场|商厦|大厦$|"
    "商业|工业|办公|商务|研发|仓储|物流|厂房|车间|地块|楼宇|"
    "客运站|地铁|车辆段|水厂|电厂|变电")
# 名称属于居委/村委会的（优先于上面的泛化关键词，避免交通公园居委被误判）
_JW_NAME = re.compile("居委|居委会|村委会|村委|居民区|社区")
ROAD_TRUNK = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}
ROAD_SECOND = {"secondary", "tertiary", "secondary_link", "tertiary_link"}

class RealDataError(RuntimeError):
    pass

@dataclass
class BuildReport:
    district: str
    district_of_unit: Optional[np.ndarray] = None
    center_stats: Dict = field(default_factory=dict)
    n_units: int = 0
    bbox_m: Tuple[float, float, float, float] = (0, 0, 0, 0)
    n_road_segments: int = 0
    n_nodes: int = 0
    n_edges: int = 0
    n_components: int = 0
    largest_share: float = 0.0
    n_landuse: int = 0
    green_share_mean: float = 0.0
    water_share_mean: float = 0.0
    road_density_mean: float = 0.0
    notes: List[str] = field(default_factory=list)

# 读数据

def list_districts() -> List[Tuple[str, int]]:
    sf = read_vector(P_VILLAGE)
    from collections import Counter
    c = Counter(x for x in sf.attrs.get(SOURCE["fields"]["village_district"], []) if x)
    return sorted(c.items(), key=lambda kv: -kv[1])

def _project_rings(rings: List[np.ndarray], lat0: float, lon0: float) -> List[np.ndarray]:
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    return [np.column_stack([(r[:, 0] - lon0) * kx, (r[:, 1] - lat0) * ky]) for r in rings]

def _load_units(district: str, rep: BuildReport):
    sf = read_vector(P_VILLAGE)
    if not sf.attrs.get("所属区e"):
        raise RealDataError("村界数据缺少所属区县字段")
    all_d = sf.attrs[SOURCE["fields"]["village_district"]]
    idx = list(range(len(all_d))) if not district else [i for i, v in enumerate(all_d) if v == district]
    if not idx:
        raise RealDataError("村界数据里没有这个区：%s（可选：%s）"
                            % (district, "、".join(d for d, _ in list_districts()[:6])))

    lat0 = float(np.mean([sf.geoms[i][0][:, 1].mean() for i in idx]))
    lon0 = float(np.mean([sf.geoms[i][0][:, 0].mean() for i in idx]))

    ids, names, streets, cx, cy, areas, rings_all = [], [], [], [], [], [], []
    for i in idx:
        rings = _project_rings(sf.geoms[i], lat0, lon0)
        px, py = polygon_centroid(rings)
        if not (np.isfinite(px) and np.isfinite(py)):
            continue
        street = sf.attrs[SOURCE["fields"]["village_street"]][i] if sf.attrs.get("所属街e") else ""
        nm = sf.attrs.get("居委_1", [""] * sf.n)[i] or sf.attrs.get("街道名", [""] * sf.n)[i] or ""
        ids.append("V%05d" % (len(ids) + 1))
        names.append(street or nm or ("单元%d" % len(ids)))
        streets.append(street)
        cx.append(px)
        cy.append(py)
        areas.append(max(polygon_area(rings), 1.0))
        rings_all.append(rings)

    rep.n_units = len(ids)
    rep.district_of_unit = np.array([all_d[i] if not district else district for i in idx[:len(ids)]], dtype=object)
    rep.notes.append("评估单元：%s的 %d 个村/居委网格（中心点来自面质心）" % (("%s " % district) if district else "全市", len(ids)))
    jw = [sf.attrs.get("居委_1", [""] * sf.n)[i] for i in idx[:len(ids)]]
    return (np.array(ids), np.array(names), np.array(streets), np.array(cx), np.array(cy),
            np.array(areas), rings_all, lat0, lon0, np.array(jw))

def _lattice_shapefile(bbox, step_m: float = 0.0, lat0: float = None, lon0: float = None):
    """没有路网数据时，在内存里造一个规则格网（经纬度），让后续流程原样跑通。

    步长按研究区大小自适应，保证每个方向至少 60 条线，否则后续"路段过少"会报错。
    """
    x0, y0, x1, y1 = bbox
    if lat0 is None or lon0 is None:
        raise ValueError(
            "_lattice_shapefile 需要显式传入 lat0/lon0（投影基准）；"
            "内置默认值在换城市时会造成上千公里偏移。")
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    pad = 1000.0
    if step_m <= 0:
        span = max(x1 - x0, y1 - y0) + 2 * pad
        step_m = max(80.0, span / 60.0)
    xs = np.arange(x0 - pad, x1 + pad + 1e-6, step_m)
    ys = np.arange(y0 - pad, y1 + pad + 1e-6, step_m)
    geoms = []
    for x in xs:
        geoms.append(np.array([[lon0 + x / kx, lat0 + (y0 - pad) / ky],
                               [lon0 + x / kx, lat0 + (y1 + pad) / ky]]))
    for y in ys:
        geoms.append(np.array([[lon0 + (x0 - pad) / kx, lat0 + y / ky],
                               [lon0 + (x1 + pad) / kx, lat0 + y / ky]]))
    n = len(geoms)
    return Shapefile(path="<格网近似>", kind="polyline", geoms=geoms,
                     attrs={"fclass": ["secondary"] * n, "oneway": ["B"] * n},
                     prj='GEOGCS["WGS 84"]', n=n)

def _load_roads(bbox, rep: BuildReport, tol_m: float = 8.0, pad: float = 0.0,
                lat0: float = None, lon0: float = None):
    """读路网、裁剪、拓扑清洗、取最大连通分量。

    lat0/lon0 必须传评估单元用的同一基准，否则路网会整体平移
    （徐汇偏 4.6 km，换到昆明会偏 1900 km，结果完全失效）。
    """
    if not P_ROADS or not os.path.exists(P_ROADS):
        sf = _lattice_shapefile(bbox, lat0=lat0, lon0=lon0)
        rep.notes.append(" 未提供路网数据，已用自适应规则格网近似；道路可达性精度会下降")
    else:
        sf = read_vector(P_ROADS)
    if lat0 is None or lon0 is None:
        raise ValueError(
            "_load_roads 需要显式传入 lat0/lon0（投影基准）；"
            "内置默认值在换城市时会造成上千公里偏移。")
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    x0, y0, x1, y1 = bbox
    # 研究区外扩：必须把 CBD 等目的地包进来，否则远郊区算出来的不是到 CBD 时间。
    # 默认 15 km；若城市中心在 15 km 之外（奉贤/金山/崇明等），按需扩展。
    if pad <= 0:
        pad = 15000.0  # 研究区外扩 15 km：必须把 CBD 等目的地包进来，否则算的不是"到 CBD"

    segs = []
    cls = []
    ow = []
    for i, g in enumerate(sf.geoms):
        if g is None or len(g) < 2:
            continue
        x = (g[:, 0] - lon0) * kx
        y = (g[:, 1] - lat0) * ky
        if x.max() < x0 - pad or x.min() > x1 + pad or y.max() < y0 - pad or y.min() > y1 + pad:
            continue
        fc = sf.attrs[SOURCE["fields"]["road_class"]][i] if sf.attrs.get(SOURCE["fields"]["road_class"]) else ""
        if fc in ("footway", "path", "steps", "cycleway", "pedestrian", "track"):
            continue  # 步行道不参与车行网络
        segs.append((x, y))
        cls.append(1 if fc in ROAD_TRUNK else (2 if fc in ROAD_SECOND else 3))
        ow.append(1 if (sf.attrs.get(SOURCE["fields"]["road_oneway"]) or [""] * sf.n)[i] in ("T", "F", "yes", "true", "1") else 0)
    if len(segs) < 50:
        raise RealDataError("裁剪后路段过少（%d），检查研究区范围" % len(segs))
    rep.n_road_segments = len(segs)

    # 端点容差合并
    key: Dict[tuple, int] = {}
    nodes: List[Tuple[float, float]] = []
    cell = tol_m

    def nid(x, y):
        gx, gy = int(round(x / cell)), int(round(y / cell))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                j = key.get((gx + dx, gy + dy))
                if j is not None:
                    px, py = nodes[j]
                    if abs(px - x) <= tol_m and abs(py - y) <= tol_m:
                        return j
        j = len(nodes)
        key[(gx, gy)] = j
        nodes.append((x, y))
        return j

    edges = []
    for (x, y), c, o in zip(segs, cls, ow):
        for k in range(len(x) - 1):
            L = math.hypot(x[k] - x[k + 1], y[k] - y[k + 1])
            if L <= 0.5:
                continue
            edges.append((nid(x[k], y[k]), nid(x[k + 1], y[k + 1]), L, c, o))

    node_xy = np.array(nodes, dtype=float)
    edges = np.array(edges, dtype=float)
    g = CSRGraph(node_xy.shape[0], edges, node_xy)
    conn = g.connectivity()
    rep.n_nodes = node_xy.shape[0]
    rep.n_edges = edges.shape[0]
    rep.n_components = int(conn["n_components"])
    rep.largest_share = conn["largest_component_share"]

    # 最大连通分量
    keep = _largest_component_mask(g)
    rep.notes.append(
        "路网：%d 段 -> %d 节点 / %d 边，连通分量 %d 个，最大占 %.1f%%；可达性只用最大连通分量（%d 节点）"
        % (rep.n_road_segments, rep.n_nodes, rep.n_edges, rep.n_components,
           rep.largest_share * 100, int(keep.sum()))
    )
    return g, keep, segs, cls

def _largest_component_mask(g: CSRGraph) -> np.ndarray:
    n = g.n_nodes
    parent = np.arange(n, dtype=np.int64)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in range(g.n_edges):
        a, b = find(int(g.edge_src[e])), find(int(g.edge_dst[e]))
        if a != b:
            parent[b] = a
    roots = np.array([find(i) for i in range(n)])
    vals, counts = np.unique(roots, return_counts=True)
    if vals.size == 0:
        return np.ones(n, dtype=bool)
    big = vals[int(np.argmax(counts))]
    return roots == big

def _load_landuse(bbox, rep: BuildReport, lat0: float = None, lon0: float = None):
    if not P_LANDUSE or not os.path.exists(P_LANDUSE):
        rep.notes.append(" 未提供土地利用数据，绿地率/建设用地/商业用地占比三项因子将缺失")
        return []
    sf = read_vector(P_LANDUSE)
    # 必须与评估单元用同一坐标基准，否则地块会整体偏移（换城市时偏移可达上千公里）
    if lat0 is None or lon0 is None:
        raise ValueError(
            "_load_landuse 需要显式传入 lat0/lon0（投影基准）；"
            "内置默认值在换城市时会造成上千公里偏移。")
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    x0, y0, x1, y1 = bbox
    out = []
    for i, g in enumerate(sf.geoms):
        if not g:
            continue
        r0 = g[0]
        x = (r0[:, 0] - lon0) * kx
        y = (r0[:, 1] - lat0) * ky
        if x.max() < x0 - 2000 or x.min() > x1 + 2000 or y.max() < y0 - 2000 or y.min() > y1 + 2000:
            continue
        fc = (sf.attrs[SOURCE["fields"]["road_class"]][i] if sf.attrs.get(SOURCE["fields"]["road_class"]) else "").lower()
        rings = [np.column_stack([((r[:, 0] - lon0) * kx), ((r[:, 1] - lat0) * ky)]) for r in g]
        out.append((fc, rings))
    rep.n_landuse = len(out)
    rep.notes.append("土地利用：研究区及周边 %d 个地块" % len(out))
    return out

# OSM POI / 交通点（从 FileGDB 读，只有装了 pyogrio 才可用）

_GDB_DIR = None

def _gdb_path() -> str:
    global _GDB_DIR
    if _GDB_DIR and os.path.exists(_GDB_DIR):
        return _GDB_DIR
    import zipfile

    tmp = os.path.join(os.environ.get("TEMP", "."), "seba_gdb")
    os.makedirs(tmp, exist_ok=True)
    target = os.path.join(tmp, "上海.gdb")
    if not os.path.exists(target):
        if not os.path.exists(GDB_ZIP):
            raise RealDataError("找不到 OSM GDB：%s" % GDB_ZIP)
        with zipfile.ZipFile(GDB_ZIP) as z:
            z.extractall(tmp)
    _GDB_DIR = target
    return target

def _parse_points(wkb_list):
    """WKB Point -> (x, y) 数组。"""
    import struct as _st

    xs = np.empty(len(wkb_list), dtype=float)
    ys = np.empty(len(wkb_list), dtype=float)
    for i, w in enumerate(wkb_list):
        if not w or len(w) < 21:
            xs[i] = ys[i] = np.nan
            continue
        xs[i], ys[i] = _st.unpack("<dd", w[5:21])
    return xs, ys

def reload_source(path: str = "") -> Dict:
    """重新读取 config/datasource.json，立刻生效（免重启）。"""
    import json as _json

    global SOURCE, P_VILLAGE, P_ROADS, P_LANDUSE, GDB_ZIP, DISTRICT_PRICE

    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "config", "datasource.json")
    if not os.path.exists(p):
        return SOURCE
    with open(p, "r", encoding="utf-8") as fh:
        cfg = _json.load(fh)
    for k, v in cfg.items():
        if k == "fields":
            SOURCE["fields"] = {**SOURCE.get("fields", {}), **(v or {})}
        elif k == "price_by_district":
            SOURCE["price_by_district"] = dict(v or {})
        else:
            SOURCE[k] = v
    P_VILLAGE = SOURCE.get("village", "")
    P_ROADS = SOURCE.get("roads", "")
    P_LANDUSE = SOURCE.get("landuse", "")
    GDB_ZIP = SOURCE.get("poi_gdb", "")
    if SOURCE.get("price_by_district"):
        DISTRICT_PRICE = dict(SOURCE["price_by_district"])
    return SOURCE

def source_summary() -> Dict:
    """当前数据源的可用性检查（给界面显示）。"""
    def ok(p):
        return bool(p) and os.path.exists(p)

    return {
        "name": SOURCE.get("name", ""),
        "units": {"path": SOURCE.get("village", ""), "ok": ok(SOURCE.get("village", ""))},
        "roads": {"path": SOURCE.get("roads", ""), "ok": ok(SOURCE.get("roads", ""))},
        "landuse": {"path": SOURCE.get("landuse", ""), "ok": ok(SOURCE.get("landuse", ""))},
        "poi": {"path": SOURCE.get("poi_gdb", ""), "ok": ok(SOURCE.get("poi_gdb", ""))},
        "fields": dict(SOURCE.get("fields", {})),
    }

def _lattice_network(x0, y0, x1, y1, step=400.0):
    """没有路网数据时，用规则格网近似-保证可达性因子仍能算出来，并在报告里注明。"""
    segs = []
    cls = []
    xs = np.arange(x0, x1 + 1e-6, step)
    ys = np.arange(y0, y1 + 1e-6, step)
    for x in xs:
        segs.append((np.array([x, x]), np.array([y0, y1])))
        cls.append(2)
    for y in ys:
        segs.append((np.array([x0, x1]), np.array([y, y])))
        cls.append(2)
    return segs, cls

def load_osm_points(layer: str, keep: set = None, exclude_names: tuple = ()):
    """读 GDB 点图层，返回 (x, y, name, fclass)。经纬度原样返回。"""
    try:
        from pyogrio.raw import read as raw_read
    except Exception as exc:  # pragma: no cover
        raise RealDataError("读取 OSM GDB 需要 pyogrio：pip install pyogrio（%s）" % exc)

    meta, fids, geoms, fields = raw_read(_gdb_path(), layer=layer)
    names = [str(x) for x in meta["fields"]]
    fc = fields[names.index("fclass")] if "fclass" in names else np.array([""] * len(geoms))
    nm = fields[names.index("name")] if "name" in names else np.array([""] * len(geoms))
    xs, ys = _parse_points(geoms)

    keep_mask = np.isfinite(xs) & np.isfinite(ys)
    if keep:
        keep_mask &= np.array([c in keep for c in fc])
    if exclude_names:
        nm_arr = np.array([str(v or "") for v in nm])
        for kw in exclude_names:
            keep_mask &= (np.char.find(nm_arr, kw) < 0)
    return xs[keep_mask], ys[keep_mask], np.array([str(v or "") for v in nm])[keep_mask], fc[keep_mask]

# 栅格化与邻域聚合

def _rings_hit(px, py, rings) -> np.ndarray:
    """多环多边形判定：各环取并集。

    OSM 派生的面常含多个外环，按"首环外环、其余为洞"处理会把大片区域误判为挖空，
    这里保守取并集（洞极少见，宁多算不漏算），并已用面积核验过绿地总量。
    """
    out = np.zeros(px.size, dtype=bool)
    for r in rings:
        if r.shape[0] < 3:
            continue
        out |= points_in_rings(px, py, [r])
    return out

def _rasterize_mask(rings_list, grid_x, grid_y, shape) -> np.ndarray:
    """把多边形集合栅格成 0/1 掩膜（按网格中心点判定）。"""
    mask = np.zeros(shape, dtype=bool)
    flat_x = grid_x.ravel()
    flat_y = grid_y.ravel()
    for rings in rings_list:
        xmin = min(r[:, 0].min() for r in rings)
        xmax = max(r[:, 0].max() for r in rings)
        ymin = min(r[:, 1].min() for r in rings)
        ymax = max(r[:, 1].max() for r in rings)
        box = ((flat_x >= xmin) & (flat_x <= xmax) & (flat_y >= ymin) & (flat_y <= ymax))
        if not box.any():
            continue
        idx = np.nonzero(box)[0]
        hit = _rings_hit(flat_x[idx], flat_y[idx], rings)
        if hit.any():
            mask.ravel()[idx[hit]] = True
    return mask

def _disc_mean(values: np.ndarray, radius_cells: int, valid: Optional[np.ndarray] = None) -> np.ndarray:
    """圆盘邻域均值（用位移累加实现，避免依赖 scipy）。"""
    h, w = values.shape
    acc = np.zeros_like(values, dtype=float)
    cnt = np.zeros_like(values, dtype=float)
    src = values.astype(float)
    vmask = np.ones_like(values, dtype=float) if valid is None else valid.astype(float)
    r = int(radius_cells)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r:
                continue
            shifted = np.zeros_like(src)
            mshift = np.zeros_like(vmask)
            ys0, ys1 = max(0, dy), min(h, h + dy)
            xs0, xs1 = max(0, dx), min(w, w + dx)
            shifted[ys0:ys1, xs0:xs1] = src[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
            mshift[ys0:ys1, xs0:xs1] = vmask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
            acc += shifted
            cnt += mshift
    return np.divide(acc, np.maximum(cnt, 1e-9))

def _simplify(pts, tol):
    """Douglas-Peucker 折线抽稀。"""
    pts = np.asarray(pts, dtype=float)
    if pts.shape[0] <= 2:
        return pts
    keep = np.zeros(pts.shape[0], dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, pts.shape[0] - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = pts[a:b + 1]
        p0, p1 = seg[0], seg[-1]
        v = p1 - p0
        L = math.hypot(v[0], v[1])
        if L < 1e-9:
            d = np.hypot(seg[:, 0] - p0[0], seg[:, 1] - p0[1])
        else:
            d = np.abs((seg[:, 0] - p0[0]) * v[1] - (seg[:, 1] - p0[1]) * v[0]) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[a + k] = True
            stack.append((a, a + k))
            stack.append((a + k, b))
    return pts[keep]

def _pack(lines, tol, digits=1):
    """折线列表 -> [[x1,y1,x2,y2,...], ...]，先抽稀再取整。"""
    out = []
    for pts in lines:
        q = _simplify(pts, tol)
        if q.shape[0] < 2:
            continue
        flat = []
        for x, y in q:
            flat.append(round(float(x), digits))
            flat.append(round(float(y), digits))
        out.append(flat)
    return out

# 主流程

def _norm_jw(t: str) -> str:
    """居委名归一：去掉居委会/居委后缀与空白。"""
    t = str(t).strip()
    for suf in ("居民委员会", "居委会", "居委"):
        if t.endswith(suf):
            t = t[: -len(suf)]
            break
    return t.replace(" ", "")

def _load_community_lonlat():
    """读取已地理编码的小区（lon/lat），按区县分组；无文件则返回 {}。"""
    import csv as _csv

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "data", "external", "community_xy.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig") as fh:
        for r in _csv.DictReader(fh):
            try:
                lon = float(r["经度"])
                lat = float(r["纬度"])
                pri = float(r["挂牌单价"])
            except (KeyError, ValueError):
                continue
            if not (120.8 < lon < 122.2 and 30.6 < lat < 31.9):
                continue
            if not (3000 < pri < 400000):
                continue
            out.setdefault((r.get("区县") or "").strip(), []).append((lon, lat, pri))
    return out

def _load_real_unit_prices(district: str, cx, cy, lat0: float, lon0: float,
                           radius: float = 800.0):
    """把小区按本区投影基准换算后匹配到评估单元，返回每单元的中位价（无则 NaN）。

    必须用与评估单元相同的 lat0/lon0，否则跨区偏移会造成漏配。
    """
    pool = _load_community_lonlat().get(district or "", [])
    n = len(cx)
    out = np.full(n, np.nan)
    if len(pool) < 20:
        return out
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    px = np.array([(lon - lon0) * kx for lon, lat, pri in pool])
    py = np.array([(lat - lat0) * ky for lon, lat, pri in pool])
    pv = np.array([pri for lon, lat, pri in pool])
    r2 = radius * radius
    for i in range(n):
        m = (px - cx[i]) ** 2 + (py - cy[i]) ** 2 <= r2
        if m.any():
            out[i] = float(np.median(pv[m]))
    return out

def build_catchment(table_path: str):
    """从官方对口表构建居委短名 -> (学校名, 班级数, 是否集团化)。"""
    import csv as _csv

    if not table_path or not os.path.exists(table_path):
        return {}
    out = {}
    for r in _csv.DictReader(open(table_path, encoding="utf-8-sig")):
        jws = (r.get("对口居委") or "").strip()
        if not jws:
            continue
        cnt = (r.get("招生班级数") or "").strip()
        grp = (r.get("是否集团化") or "0").strip() == "1"
        for jw in jws.replace("、", "|").replace("，", "|").split("|"):
            k = _norm_jw(jw)
            if k:
                out[k] = (r.get("学校名称", ""), float(cnt) if cnt.isdigit() else float("nan"), grp)
    return out

def match_catchment(jwnames, table_path):
    """把单元居委名匹配到对口学校；返回 (班级数, 集团化, 是否命中) 三个数组。"""
    mp = build_catchment(table_path)
    n = len(jwnames)
    cls = np.full(n, np.nan)
    grp = np.zeros(n)
    hit = np.zeros(n, dtype=bool)
    if not mp:
        return cls, grp, hit
    keys = sorted(mp.keys(), key=len, reverse=True)
    for i, jw in enumerate(jwnames):
        k = _norm_jw(jw)
        if not k:
            continue
        for key in keys:
            if key == k or key in k or k in key:
                nm, c, g = mp[key]
                cls[i] = c
                grp[i] = 1.0 if g else 0.0
                hit[i] = True
                break
    return cls, grp, hit

def load_schools(name_table: str = "") -> dict:
    """从 OSM 面要素提取学校/幼儿园质心；可选地匹配官方学校名单补充属性。

    返回 {"x","y","name","kind","class_cnt","group"}（经纬度，未投影）。
    结果缓存在 cache_schools.npz，避免每次重解析 GDB。
    """
    import csv as _csv
    import glob as _glob

    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache_schools.npz")
    if os.path.exists(cache):
        d = np.load(cache, allow_pickle=True)
        xs, ys, nm, fc = d["x"], d["y"], d["name"], d["fclass"]
    else:
        try:
            from pyogrio.raw import read as raw_read
            from shapely import wkb as _wkb
        except Exception as exc:
            raise RealDataError("提取学校点位需要 pyogrio 与 shapely：%s" % exc)
        meta, fids, geoms, fields = raw_read(_gdb_path(), layer="gis_osm_pois_a_free")
        names = [str(x) for x in meta["fields"]]
        fcv = fields[names.index("fclass")]
        nmv = fields[names.index("name")]
        xs, ys, nm, fc = [], [], [], []
        for i, c in enumerate(fcv):
            if c not in ("school", "kindergarten"):
                continue
            try:
                p = _wkb.loads(bytes(geoms[i])).centroid
            except Exception:
                continue
            xs.append(p.x); ys.append(p.y)
            nm.append(str(nmv[i] or "")); fc.append(str(c))
        xs = np.array(xs); ys = np.array(ys); nm = np.array(nm); fc = np.array(fc)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        np.savez(cache, x=xs, y=ys, name=nm, fclass=fc)

    n = xs.size
    class_cnt = np.full(n, np.nan)
    group = np.zeros(n)
    if name_table and os.path.exists(name_table):
        rows = list(_csv.DictReader(open(name_table, encoding="utf-8-sig")))
        def norm(t):
            t = str(t)
            for w in ("上海市", "静安区", "闸北", "（", "）", "(", ")", " "):
                t = t.replace(w, "")
            return t
        idx = {}
        for i in range(n):
            k = norm(nm[i])
            if k:
                idx.setdefault(k, []).append(i)
        hit = 0
        for r in rows:
            key = norm(r.get("学校名称", ""))
            for i in idx.get(key, []):
                v = (r.get("招生班级数") or "").strip()
                if v.isdigit():
                    class_cnt[i] = float(v)
                    hit += 1
                group[i] = 1.0 if (r.get("是否集团化") or "0").strip() == "1" else 0.0
        return {"x": xs, "y": ys, "name": nm, "kind": fc,
                "class_cnt": class_cnt, "group": group, "matched": hit}

    return {"x": xs, "y": ys, "name": nm, "kind": fc,
            "class_cnt": class_cnt, "group": group, "matched": 0}

def build_district_dataset(
    district= "长宁区",
    cell_m: float = 100.0,
    radius_m: float = 500.0,
    obs_share: float = 0.70,
    seed: int = 20261117,
) -> Tuple[Dataset, BuildReport]:
    rep = BuildReport(district=district)
    rng = np.random.default_rng(seed)

    (ids, names, streets, cx, cy, areas, rings_all, lat0, lon0, jwnames) = _load_units(district, rep)
    x0, y0 = float(cx.min()), float(cy.min())
    x1, y1 = float(cx.max()), float(cy.max())
    rep.bbox_m = (x0, y0, x1, y1)

    # 自适应裁剪范围：把城市中心包进路网，否则远郊区的可达性因子会失真
    _cbd_lon, _cbd_lat = SOURCE["cbd"][0], SOURCE["cbd"][1]
    _kx = 111320.0 * math.cos(math.radians(lat0))
    _ky = 110540.0
    _cx = (_cbd_lon - lon0) * _kx
    _cy = (_cbd_lat - lat0) * _ky
    _dx = max(0.0, x0 - _cx, _cx - x1)
    _dy = max(0.0, y0 - _cy, _cy - y1)
    _need = math.hypot(_dx, _dy) + 5000.0
    _pad = max(15000.0, min(90000.0, _need))
    graph, keep, segs, cls = _load_roads((x0, y0, x1, y1), rep, pad=_pad,
                                         lat0=lat0, lon0=lon0)

    # 校验：CBD 必须落在路网范围内，否则可达性因子没有意义
    cbd_pt = np.array([[(SOURCE["cbd"][0] - lon0) * 111320.0 * math.cos(math.radians(lat0)),
                        (SOURCE["cbd"][1] - lat0) * 110540.0]])
    d_cbd_node = float(np.min(np.hypot(graph.node_xy[:, 0] - cbd_pt[0, 0],
                                       graph.node_xy[:, 1] - cbd_pt[0, 1])))
    if d_cbd_node > 1500:
        rep.notes.append(" 人民广场距最近路网节点 %.0f 米，可达性因子可能失真（请扩大裁剪范围）" % d_cbd_node)
    else:
        rep.notes.append("CBD 锚点已落在路网内（距最近节点 %.0f 米）" % d_cbd_node)
    landuse = _load_landuse((x0, y0, x1, y1), rep, lat0=lat0, lon0=lon0)

    # OSM 点图层：地铁站 / 商业设施 / 公交站
    kx0 = 111320.0 * math.cos(math.radians(lat0))
    ky0 = 110540.0
    poi_xy = {}
    try:
        for key, layer, keepset, exc in (
            ("metro", "gis_osm_transport_free", {"railway_station"}, RAIL_EXCLUDE),
            ("shop", "gis_osm_pois_free", SHOP_CLS, ()),
            ("bus", "gis_osm_transport_free", {"bus_stop"}, ()),
        ):
            lon, lat, nm, fc = load_osm_points(layer, keep=keepset, exclude_names=exc)
            px = (lon - lon0) * kx0
            py = (lat - lat0) * ky0
            m = (px > x0 - 3000) & (px < x1 + 3000) & (py > y0 - 3000) & (py < y1 + 3000)
            poi_xy[key] = (px[m], py[m], nm[m])
            rep.notes.append("OSM %s：%d 个点（研究区及周边 3 km）" % (key, int(m.sum())))
    except RealDataError as exc2:
        rep.notes.append(" 未载入 OSM 点图层（%s），地铁与商业因子将缺失" % exc2)

    # 学区：学校点位（面要素质心）+ 官方招生规模
    sch = None
    try:
        _cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")
        _cands = []
        if district:
            _cands.append(os.path.join(_cfg, "catchment", "%s.csv" % district))
        _cands.append(os.path.join(_cfg, "catchment", "全市.csv"))
        # 静安旧表只含静安的招生班数与集团化属性，仅供静安使用；
        # 其他区若借用，会把静安的对口关系套到别的区，属跨区污染。
        if district == "静安区":
            _cands.append(os.path.join(_cfg, "school_jingan.csv"))
        tbl = next((p for p in _cands if os.path.exists(p)), "")
        sch = load_schools(tbl if os.path.exists(tbl) else "")
        sx = (sch["x"] - lon0) * kx0
        sy = (sch["y"] - lat0) * ky0
        m = (sx > x0 - 5000) & (sx < x1 + 5000) & (sy > y0 - 5000) & (sy < y1 + 5000)
        sch["px"] = sx[m]; sch["py"] = sy[m]
        sch["pclass"] = sch["class_cnt"][m]; sch["pgroup"] = sch["group"][m]
        sch["pname"] = sch["name"][m]; sch["pkind"] = sch["kind"][m]
        rep.notes.append("学区：学校/幼儿园 %d 处（研究区周边 5 km），其中 %d 所匹配到官方招生规模"
                         % (int(m.sum()), sch.get("matched", 0)))
    except Exception as exc3:
        rep.notes.append(" 未载入学校图层（%s），学区因子将缺失" % exc3)

    # 单元级学区因子：到最近小学距离、800 m 内学校数、最近小学招生规模
    sch_dist = np.full(len(ids), np.nan)
    sch_cnt = np.zeros(len(ids))
    sch_class = np.full(len(ids), np.nan)
    sch_group = np.zeros(len(ids))
    sch_catch = np.zeros(len(ids))
    if sch is not None and sch["px"].size:
        px_, py_ = sch["px"], sch["py"]
        for i in range(len(ids)):
            d = np.hypot(px_ - cx[i], py_ - cy[i])
            j = int(np.argmin(d))
            sch_dist[i] = d[j]
            sch_cnt[i] = (d <= 800.0).sum()
            sch_class[i] = sch["pclass"][j]
            sch_group[i] = sch["pgroup"][j]
        med_cls = np.nanmedian(sch_class) if np.isfinite(sch_class).any() else 0.0
        sch_class = np.where(np.isfinite(sch_class), sch_class, med_cls)
        rep.notes.append("学区：单元到最近学校距离中位 %.0f m，800 m 内平均 %.1f 所"
                         % (float(np.nanmedian(sch_dist)), float(sch_cnt.mean())))

        # 对口小学（按居委名匹配）
        cls_c, grp_c, hit_c = match_catchment(jwnames, tbl if os.path.exists(tbl) else "")
        if hit_c.any():
            sch_class = np.where(hit_c, cls_c, sch_class)
            sch_group = np.where(hit_c, grp_c, sch_group)
            sch_catch = hit_c.astype(float)
            # 未匹配单元用已匹配单元的中位数填充，避免整列 NaN；
            # 是否匹配本身由 sch_catchment 因子单独表达
            _m = np.isfinite(sch_class)
            if _m.any():
                sch_class = np.where(_m, sch_class, float(np.nanmedian(sch_class[_m])))
            sch_class = np.nan_to_num(sch_class, nan=0.0)
            rep.notes.append("学区：%d/%d 个单元匹配到对口小学（覆盖率 %.0f%%）"
                             % (int(hit_c.sum()), len(hit_c), hit_c.mean() * 100))
        else:
            sch_catch = np.zeros(len(ids))
            sch_class = np.zeros(len(ids))
    else:
        sch_catch = np.zeros(len(ids))

    # 栅格（覆盖研究区，每边留 1 km）
    pad = 1000.0
    gx0, gy0 = x0 - pad, y0 - pad
    nx = int((x1 - x0 + 2 * pad) / cell_m) + 1
    ny = int((y1 - y0 + 2 * pad) / cell_m) + 1
    xs = gx0 + (np.arange(nx) + 0.5) * cell_m
    ys = gy0 + (np.arange(ny) + 0.5) * cell_m
    GX, GY = np.meshgrid(xs, ys, indexing="xy")
    shape = GX.shape

    green_rings = [r for fc, r in landuse if fc in GREEN_CLS]
    water_rings = [r for fc, r in landuse if fc in WATER_CLS]
    built_rings = [r for fc, r in landuse if fc in BUILT_CLS]
    green = _rasterize_mask(green_rings, GX, GY, shape)
    water = _rasterize_mask(water_rings, GX, GY, shape)
    built = _rasterize_mask(built_rings, GX, GY, shape)
    comm_rings = [r for fc, r in landuse if fc in ("commercial", "retail", "industrial")]
    comm = _rasterize_mask(comm_rings, GX, GY, shape) if comm_rings else np.zeros_like(built)
    # 居住用地：用于判定单元是否为住宅用地（剔除公园、商场、学校、办事处等）
    res_rings = [r for fc, r in landuse if str(fc).lower() == "residential"]
    res = _rasterize_mask(res_rings, GX, GY, shape) if res_rings else np.zeros_like(built)

    # 道路长度栅格
    road_len = np.zeros(shape, dtype=float)
    for (x, y) in segs:
        for k in range(len(x) - 1):
            mx, my = (x[k] + x[k + 1]) / 2, (y[k] + y[k + 1]) / 2
            i = int((mx - gx0) / cell_m)
            j = int((my - gy0) / cell_m)
            if 0 <= i < nx and 0 <= j < ny:
                road_len[j, i] += math.hypot(x[k] - x[k + 1], y[k] - y[k + 1])

    r_cells = max(1, int(round(radius_m / cell_m)))
    green_share = _disc_mean(green.astype(float), r_cells)
    water_share = _disc_mean(water.astype(float), r_cells)
    built_share = _disc_mean(built.astype(float), r_cells)
    comm_share = _disc_mean(comm.astype(float), r_cells)
    r_near = max(1, int(round(250.0 / cell_m)))
    res_share = _disc_mean(res.astype(float), r_near)
    road_km_km2 = _disc_mean(road_len, r_cells) * 1000.0 / (cell_m ** 2)

    # 单元级取值（最近网格）
    ui = np.clip(((cx - gx0) / cell_m).astype(int), 0, nx - 1)
    uj = np.clip(((cy - gy0) / cell_m).astype(int), 0, ny - 1)
    f_green = green_share[uj, ui]
    f_water = water_share[uj, ui]
    f_built = built_share[uj, ui]
    f_road = road_km_km2[uj, ui]
    f_comm = comm_share[uj, ui]
    f_res = res_share[uj, ui]
    rep.green_share_mean = float(f_green.mean())
    rep.water_share_mean = float(f_water.mean())
    rep.road_density_mean = float(f_road.mean())
    rep.notes.append(
        "单元因子已生成：绿地率均值 %.1f%%、建设用地占比 %.1f%%、路网密度均值 %.1f km/km²（土地利用图层不含水体，水面率置零）"
        % (f_green.mean() * 100, f_built.mean() * 100, f_road.mean())
    )

    # 图层
    nodes_z = np.column_stack([graph.node_xy[:, 0], graph.node_xy[:, 1]])
    sub = keep
    remap = -np.ones(graph.n_nodes, dtype=np.int64)
    remap[sub] = np.arange(int(sub.sum()))
    e_keep = (remap[graph.edge_src] >= 0) & (remap[graph.edge_dst] >= 0)
    edges_kept = np.column_stack([
        remap[graph.edge_src[e_keep]], remap[graph.edge_dst[e_keep]],
        graph.edge_len[e_keep], graph.edge_cls[e_keep],
        np.zeros(int(e_keep.sum())),
    ])
    road_layer = LayerData(
        layer_id="road_net", layer_type="network", crs="本地平面坐标（米）",
        asof_date="2024", version="sh2024",
        fields=["length", "speed_class", "oneway"],
        nodes=nodes_z[sub], edges=edges_kept,
    )
    # 人民广场（CBD 锚点）
    CBD_LON, CBD_LAT = SOURCE["cbd"]
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    cbd_xy = np.array([[(CBD_LON - lon0) * kx, (CBD_LAT - lat0) * ky]])
    cbd_layer = LayerData(
        layer_id="poi_cbd", layer_type="point", crs="本地平面坐标（米）",
        asof_date="2024", version="sh2024", fields=[],
        x=cbd_xy[:, 0], y=cbd_xy[:, 1],
    )

    grid = Grid(nx=nx, ny=ny, cell=cell_m, x0=gx0, y0=gy0)
    units = UnitTable(
        unit_id=ids, ix=ui, iy=uj, x=cx, y=cy,
        area=areas, admin_code=streets, name=np.array(jwnames), use_type=np.array(["住宅"] * len(ids)),
        population=np.round(areas / 120.0).astype(float),  # 按人均 120 ㎡ 粗估
        asof_date="2024",
    )

    # 成交（价格水平锚定真实区级均价，区内差异由真实网络可达性驱动）
    if district:
        base = DISTRICT_PRICE.get(district, 60000.0)
    else:
        # 全市：按各区评估单元数量加权各区真实均价
        import collections as _c

        cnt = _c.Counter(rep.district_of_unit.tolist())
        wsum = sum(DISTRICT_PRICE.get(d, 60000.0) * n for d, n in cnt.items())
        base = wsum / max(sum(cnt.values()), 1)
    # 潜在可达性：从人民广场出发在真实路网上做一次 Dijkstra，得到真实车行时间
    cbd_xy_m = np.array([[(SOURCE["cbd"][0] - lon0) * 111320.0 * math.cos(math.radians(lat0)),
                          (SOURCE["cbd"][1] - lat0) * 110540.0]])
    from .net import snap_points

    w_drive = graph.weights("drive")
    cbd_node = int(snap_points(cbd_xy_m[:, 0], cbd_xy_m[:, 1], graph.node_xy, 1e12).node[0])
    dist_t = graph.dijkstra(cbd_node, w_drive)
    us = snap_points(cx, cy, graph.node_xy, 800.0)
    t_true = dist_t[us.node]
    finite = np.isfinite(t_true)
    t_true = np.where(finite, t_true, np.nanmedian(t_true[finite]) if finite.any() else 30.0)

    # 真实地铁可达性：到最近轨道站的最短网络时间（多源取最小）
    t_metro = np.full(len(ids), np.inf)
    if "metro" in poi_xy and poi_xy["metro"][0].size:
        mx, my, _ = poi_xy["metro"]
        m_node = np.unique(snap_points(mx, my, graph.node_xy, 1e12).node)
        for (a, b), buf in graph.iter_dijkstra_many(m_node, w_drive, limit=40.0, chunk=32):
            t_metro = np.minimum(t_metro, np.nanmin(buf, axis=0)[us.node])
    fin = np.isfinite(t_metro)
    t_metro = np.where(fin, t_metro, np.nanmedian(t_metro[fin]) if fin.any() else 30.0)

    # 真实商业密度：1 km 内商业设施数量
    shop_cnt = np.zeros(len(ids))
    if "shop" in poi_xy and poi_xy["shop"][0].size:
        sx, sy, _ = poi_xy["shop"]
        for k in range(sx.size):
            shop_cnt += (np.hypot(cx - sx[k], cy - sy[k]) <= 1000.0)

    # 中心地理论：识别分级中心地并计算加权可达性
    from .centralplace import center_gravity, detect_centers

    cp_stats = {}
    cf = None
    cp_g = {1: np.full(len(ids), np.nan), 2: np.full(len(ids), np.nan), 3: np.full(len(ids), np.nan)}
    cp_high = np.zeros(len(ids))
    if "shop" in poi_xy and poi_xy["shop"][0].size:
        hubs = []
        try:
            hlon, hlat, hname, hfc = load_osm_points(
                "gis_osm_transport_free", keep={"airport", " railway_station".strip()})
            for i in range(len(hlon)):
                if hfc[i] == "airport" or any(k in str(hname[i]) for k in
                                              ("火车站", "虹桥站", "上海站", "南站", "西站")):
                    hubs.append(((hlon[i] - lon0) * kx0, (hlat[i] - lat0) * ky0, 1500.0))
        except Exception:
            pass
        # 中心地必须在全市尺度识别：徐汇居民会去南京东路、陆家嘴，不只在本区消费
        alon, alat, anm, afc = load_osm_points("gis_osm_pois_free", keep=SHOP_CLS)
        sx0 = (alon - lon0) * kx0
        sy0 = (alat - lat0) * ky0
        ref = []
        if "metro" in poi_xy:
            mx0, my0, mn0 = poi_xy["metro"]
            ref = [(mx0[i], my0[i], str(mn0[i])) for i in range(mx0.size)]
        cf = detect_centers(sx0, sy0, afc, names=ref,
                            bandwidth_m=1500.0, nms_m=1200.0, min_poi_1km=10,
                            exclude_xy=hubs)
        cp_stats = dict(cf.stats)
        by = cf.by_level()
        for lvl in (1, 2, 3):
            pts = by[lvl]
            if not pts:
                continue
            cn = snap_points(np.array([c.x for c in pts]), np.array([c.y for c in pts]),
                             graph.node_xy, 1e12).node
            tmin = np.full(len(ids), np.inf)
            for (a, b), buf in graph.iter_dijkstra_many(np.unique(cn), w_drive, limit=60.0, chunk=16):
                tmin = np.minimum(tmin, buf[:, us.node].min(axis=0))
            fin2 = np.isfinite(tmin)
            tmin = np.where(fin2, tmin, 999.0)
            cp_g[lvl] = tmin
            cp_high = np.where(tmin <= 30.0, float(lvl), cp_high)
        rep.notes.append("中心地：识别 %s，加权可达性已生成"
                         % "、".join("%d 级 %d 个" % (k, v) for k, v in
                                    ((1, cp_stats.get("n_L1", 0)), (2, cp_stats.get("n_L2", 0)),
                                     (3, cp_stats.get("n_L3", 0)))))
        rep.center_stats = cp_stats

    lw = {1: 1.0, 2: 0.5, 3: 0.25}
    cp_grav = np.zeros(len(ids))
    for lvl, wgt in lw.items():
        cp_grav += wgt * np.exp(-0.06 * np.clip(cp_g[lvl], 0, 180))

    spatial = _smooth_xy(cx, cy, rng)
    z = (-0.30 * _z(np.log1p(t_true))
         + 0.22 * _z(cp_grav)
         + 0.10 * _z(cp_high)
         - 0.26 * _z(np.log1p(t_metro))
         + 0.24 * _z(np.log1p(shop_cnt))
         + 0.18 * _z(f_comm)
         + 0.16 * _z(f_green)
         + 0.12 * _z(f_road)
         + 0.10 * _z(f_built))
    logp = np.log(base) + 0.44 * z + 0.12 * spatial + rng.standard_t(5, len(ids)) * 0.075
    price_pm2 = np.exp(logp)
    # 水平校准：让估算价格的均值正好等于区级官方均价（对数正态会自带系统性上移）
    price_pm2 *= base / price_pm2.mean()

    # 按用地性质剔除非住宅单元
    _names_arr = [str(x) for x in jwnames]
    is_res = np.ones(len(ids), dtype=bool)
    _why = []
    for _i, _nm in enumerate(_names_arr):
        if _JW_NAME.search(_nm):
            # 居委/村委会是住宅单元的强信号；即使名字里带公园商业等词，
            # 也优先按住宅处理（例如交通公园居委）。
            is_res[_i] = True
        elif _NONRES_NAME.search(_nm):
            is_res[_i] = False
            _why.append("名称")
        else:
            is_res[_i] = bool(f_res[_i] >= RES_MIN_SHARE)
    units.use_type = np.where(is_res, "住宅", "非住宅")
    rep.notes.append("用地性质：%d/%d 个单元判定为住宅用地，%d 个非住宅单元（公园、"
                     "商业、学校、办公等）已排除，不参与估值与统计"
                     % (int(is_res.sum()), len(ids), int((~is_res).sum())))

    # 若已具备小区级真实挂牌价，优先用真实价
    real_arr = _load_real_unit_prices(district, cx, cy, lat0, lon0)
    real_cov = float(np.isfinite(real_arr).mean()) if len(ids) else 0.0
    if real_cov >= 0.30:
        price_pm2 = np.where(np.isfinite(real_arr), real_arr, price_pm2)
        has = np.isfinite(real_arr)
        _src = "小区级挂牌价（高德地理编码 + 公开数据集）"
        rep.notes.append("价格：%d/%d 个单元使用真实小区挂牌价（覆盖率 %.0f%%）"
                         % (int(np.isfinite(real_arr).sum()), len(ids), real_cov * 100))
    else:
        has = rng.random(len(ids)) < obs_share
        _src = "估算（水平锚定区级均价）"
        rep.notes.append("价格：真实小区价覆盖率仅 %.0f%%，本区仍用估算价格"
                         % (real_cov * 100))
    has = has & is_res
    idx = np.nonzero(has)[0]
    obs = ObsTable(
        unit_idx=idx,
        price=price_pm2[idx] * 90.0,
        unit_price=price_pm2[idx],
        deal_date=np.array(["2024-06-15"] * idx.size),
        price_type=np.array(["listing"] * idx.size),
        source=np.array([_src] * idx.size),
        weight=np.ones(idx.size),
    )

    layers = {"road_net": road_layer, "poi_cbd": cbd_layer}
    for key, lid, note in (("metro", "poi_metro", "地铁站"),
                           ("shop", "poi_shop", "商业设施"),
                           ("bus", "poi_bus", "公交站")):
        if key in poi_xy and poi_xy[key][0].size:
            lx, ly, ln = poi_xy[key]
            layers[lid] = LayerData(
                layer_id=lid, layer_type="point", crs="本地平面坐标（米）",
                asof_date="2024", version="sh2024", fields=["name"],
                x=lx, y=ly, aux_meta={"display_name": note},
            )

    if sch is not None and sch["px"].size:
        layers["poi_school"] = LayerData(
            layer_id="poi_school", layer_type="point", crs="本地平面坐标（米）",
            asof_date="2024", version="sh2024", fields=["name"],
            x=sch["px"], y=sch["py"], aux_meta={"display_name": "学校与幼儿园"},
        )

    ds = Dataset(
        grid=grid, units=units, obs=obs,
        layers=layers,
        crs="本地平面坐标（米）",
        project_name=(district or "上海全市"),
        unit_attrs={
            "green_share": f_green,
            "water_share": f_water,
            "built_share": f_built,
            "road_km_km2": f_road,
            "comm_share": f_comm,
            "metro_time": t_metro,
            "shop_1km": shop_cnt,
            "cp_gravity": cp_grav,
            "cp_high_level": cp_high,
            "cp_L1_time": cp_g[1],
            "sch_dist": sch_dist,
            "sch_cnt_800": sch_cnt,
            "sch_class_cnt": sch_class,
            "sch_group": sch_group,
            "sch_catchment": sch_catch,
            "res_share": f_res,
        },
    )
    if "metro" in poi_xy and poi_xy["metro"][0].size:
        rep.notes.append("地铁可达性：到最近站中位 %.1f 分钟（真实路网最短路）" % float(np.median(t_metro)))
    rep.notes.append("商业设施：1 km 内平均 %.1f 个" % float(shop_cnt.mean()))
    if _src.startswith("估算"):
        rep.notes.append("价格：水平锚定 %s 2024 年二手住宅网签均价 %.0f 元/㎡"
                         "（区内差异由真实因子驱动）" % (district or "全市加权", base))
    # 底图（抽稀后供前端绘制）
    bm = {"boundaries": [], "roads": [], "centers": [], "unit_polys": [], "water": []}
    big = len(ids) > 1500          # 全市尺度不逐块画，否则传输体积过大

    # 单元面：前端用来填色（比在质心画方块好看得多，也忠实于真实边界）
    if not big:
        polys = []
        for rings in rings_all:
            if rings:
                polys.append(_simplify(rings[0], 6.0))
        bm["unit_polys"] = _pack(polys, 0.0, digits=0)
        bm["boundaries"] = bm["unit_polys"]

    # 路网：区级给全量，市级只给主干，避免传输爆掉
    try:
        m = 2500.0

        def _near(xa, ya):
            return (xa.max() > x0 - m and xa.min() < x1 + m
                    and ya.max() > y0 - m and ya.min() < y1 + m)

        keep_cls = (1, 2, 3) if not big else (1, 2)
        roads = []
        for (x, y), c in zip(segs, cls):
            if c not in keep_cls:
                continue
            if _near(x, y):
                roads.append(np.column_stack([x, y]))
        bm["roads"] = _pack(roads, 8.0 if not big else 20.0, digits=0)
    except Exception:
        pass

    # 水系：识别"这是哪儿"最有效的视觉锚点（黄浦江、苏州河）
    try:
        from pyogrio.raw import read as _rr
        from shapely import wkb as _wkb

        meta_w, fids_w, geoms_w, fields_w = _rr(_gdb_path(), layer="gis_osm_water_a_free")
        mw = 2500.0
        wp = []
        for wb in geoms_w:
            try:
                g = _wkb.loads(bytes(wb))
                if g.is_empty:
                    continue
                gx0, gy0, gx1, gy1 = g.bounds
                lx0 = (gx0 - lon0) * kx0
                lx1 = (gx1 - lon0) * kx0
                ly0 = (gy0 - lat0) * ky0
                ly1 = (gy1 - lat0) * ky0
                if lx1 < x0 - mw or lx0 > x1 + mw or ly1 < y0 - mw or ly0 > y1 + mw:
                    continue
                polys_w = [g] if g.geom_type == "Polygon" else list(g.geoms)
                for pg in polys_w:
                    rr = np.asarray(pg.exterior.coords, dtype=float)
                    rr = np.column_stack([(rr[:, 0] - lon0) * kx0, (rr[:, 1] - lat0) * ky0])
                    rr = _simplify(rr, 15.0 if not big else 40.0)
                    if rr.shape[0] >= 3:
                        wp.append(rr)
                if len(wp) > 900:
                    break
            except Exception:
                continue
        bm["water"] = _pack(wp, 0.0, digits=0)
    except Exception:
        pass

    # 展示用中心地：全市 NMS（1.2 km）会把跨区界的商业簇合并到邻区
    # （静安寺与陕西南路只隔约 350 m，中心点被判到区界以南），单区地图上
    # 就会一个中心地都看不到。这里用本区周边 3 km 的商业点再识别一次，
    # 只保留落在区界内的中心，供底图标注；模型里的可达性因子仍用全市
    # 中心地，两者口径不同。
    bm["centers"] = []
    if "shop" in poi_xy and poi_xy["shop"][0].size:
        try:
            lcf = detect_centers(
                poi_xy["shop"][0], poi_xy["shop"][1],
                np.array([""] * poi_xy["shop"][0].size, dtype=object),
                bandwidth_m=600.0, nms_m=600.0, min_poi_1km=4,
                merge_m=600.0, names=ref)

            def _inside(px: float, py: float) -> bool:
                for rings in rings_all:
                    if rings and points_in_rings(
                            np.array([px]), np.array([py]), [rings[0]])[0]:
                        return True
                return False

            kept = [c for c in lcf.centers if _inside(c.x, c.y)]
            kept.sort(key=lambda c: -c.score)
            kept = kept[:12]
            for i, c in enumerate(kept):
                lvl = 2 if i == 0 else 3
                if cf is not None:
                    near = [k.level for k in cf.centers
                            if math.hypot(k.x - c.x, k.y - c.y) <= 1500.0]
                    if near:
                        lvl = min(near)
                # 最近地铁超过 1.2 km 时不署名，避免把邻站名字贴到别的商圈上
                nm = c.name or ""
                if nm and ref:
                    if min(math.hypot(m[0] - c.x, m[1] - c.y) for m in ref) > 1200.0:
                        nm = ""
                bm["centers"].append({
                    "x": round(c.x, 1), "y": round(c.y, 1),
                    "level": lvl, "name": nm, "src": "local"})
        except Exception:
            bm["centers"] = []
    ds.basemap = bm

    if _src.startswith("估算"):
        rep.notes.append("成交：%d 条（%.0f%% 单元有观测），为生成数据，仅用于验证方法链路"
                         % (idx.size, obs_share * 100))
    else:
        rep.notes.append("成交：%d 条，采用小区级真实挂牌价，非生成数据"
                         % idx.size)
    return ds, rep

def _z(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    sd = v.std()
    return (v - v.mean()) / sd if sd > 0 else v * 0.0

def _smooth_xy(x: np.ndarray, y: np.ndarray, rng, waves: int = 4) -> np.ndarray:
    """二维平滑场：几组不同波长与方向的余弦叠加，保证在空间上连续（这样才能检验空间诊断）。"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    X = (x - x.min()) / max(x.max() - x.min(), 1.0)
    Y = (y - y.min()) / max(y.max() - y.min(), 1.0)
    out = np.zeros_like(X)
    for _ in range(waves):
        fx, fy = rng.uniform(0.8, 2.6, 2)
        ph = rng.uniform(0, 2 * np.pi)
        amp = rng.normal(0, 1)
        out += amp * np.cos(2 * np.pi * (fx * X + fy * Y) + ph)
    sd = out.std()
    return (out - out.mean()) / sd if sd > 0 else out * 0.0
