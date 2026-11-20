# -*- coding: utf-8 -*-
"""数据接入向导的识别引擎。

用户丢上来一堆文件，系统要做三件事：
  1. 认出每个文件是什么（评估单元边界 / 路网 / 土地利用 / POI / 成交表）
  2. 认出每个字段是什么意思（哪怕是“道路等级”而不是 fclass，或 ALAND 这种缩写）
  3. 给出置信度，让用户在界面上确认或改

判据有两条：字段名的语义相似度 + 字段取值的形态特征。
两条都不看的话，只靠名字换个语言就废了；只靠取值，遇到英文城市又认不出。
"""

from __future__ import annotations

import csv
import json
import math
import os
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["FileInfo", "inspect_file", "guess_roles", "build_datasource", "ROLES"]


# ---------------------------------------------------------------------------
# 角色定义：系统需要哪些数据、每类数据需要哪些字段
# ---------------------------------------------------------------------------

ROLES: Dict[str, Dict[str, Any]] = {
    "units": {
        "label": "评估单元边界",
        "geom": "Polygon",
        "required": True,
        "fields": {
            "district": {"label": "区县字段", "required": True},
            "street": {"label": "街道/镇字段", "required": False},
            "name": {"label": "村居名称", "required": False},
        },
    },
    "roads": {
        "label": "路网",
        "geom": "Polyline",
        "required": False,
        "fields": {
            "road_class": {"label": "道路等级", "required": False},
            "oneway": {"label": "单行标志", "required": False},
        },
    },
    "landuse": {
        "label": "土地利用",
        "geom": "Polygon",
        "required": False,
        "fields": {
            "landuse_class": {"label": "用地类型", "required": False},
        },
    },
    "poi": {
        "label": "POI 点位",
        "geom": "Point",
        "required": False,
        "fields": {
            "category": {"label": "设施类别", "required": False},
            "name": {"label": "名称", "required": False},
        },
    },
    "obs": {
        "label": "成交/价格表",
        "geom": "None",
        "required": False,
        "fields": {
            "unit_id": {"label": "单元编号", "required": False},
            "x": {"label": "X / 经度", "required": False},
            "y": {"label": "Y / 纬度", "required": False},
            "price": {"label": "成交总价", "required": True},
            "unit_price": {"label": "成交单价", "required": False},
            "date": {"label": "成交日期", "required": False},
        },
    },
}

# 字段名同义词库：中英文、常见缩写、各地习惯叫法
SYN: Dict[str, List[str]] = {
    "district": ["区县", "所属区", "行政区", "区", "district", "county", "qu", "区名", "ADM2", "NAME_2"],
    "street": ["街道", "镇", "乡", "所属街", "街道名", "town", "township", "subdistrict", "street", "ADM3"],
    "name": ["名称", "居委", "居委会", "村", "社区", "网格", "name", "village", "community", "NAME", "地名"],
    "road_class": ["等级", "道路等级", "类型", "类别", "fclass", "class", "type", "road_class",
                   "highway", "roadtype", "道路类型", "路网等级", "grade"],
    "oneway": ["单行", "单向", "oneway", "one_way", "oneway_flag", "通行方向", "direction", "单向通行"],
    "landuse_class": ["用地", "用地类型", "土地类型", "地类", "功能", "fclass", "class", "type",
                "landuse", "lu_class", "用地性质", "规划用途"],
    "category": ["类别", "类型", "分类", "fclass", "class", "category", "poi_type", "设施类型", "业态"],
    "unit_id": ["单元", "编号", "id", "unit", "unit_id", "code", "宗地号", "不动产单元号", "parcel"],
    "x": ["x", "经度", "lon", "lng", "longitude", "x坐标", "东经", "横坐标"],
    "y": ["y", "纬度", "lat", "latitude", "y坐标", "北纬", "纵坐标"],
    "price": ["总价", "成交价", "价格", "price", "total_price", "amount", "成交金额", "挂牌价"],
    "unit_price": ["单价", "均价", "楼面价", "unit_price", "price_pm2", "元/平", "单价元"],
    "date": ["日期", "成交日期", "时间", "date", "deal_date", "签约日期", "time"],
}

# 取值形态的已知词表
OSM_ROAD = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential",
            "service", "unclassified", "motorway_link", "trunk_link", "primary_link",
            "secondary_link", "tertiary_link", "living_street", "pedestrian", "footway"}
CN_ROAD = {"高速", "国道", "省道", "县道", "乡道", "主干路", "次干路", "支路", "快速路",
           "城市主干道", "城市次干道", "一级公路", "二级公路", "三级公路", "四级公路",
           "步行道", "小区路"}
OSM_LANDUSE = {"residential", "commercial", "industrial", "farmland", "forest", "grass",
               "park", "retail", "water", "cemetery", "military", "quarry", "orchard",
               "meadow", "scrub", "wetland", "construction", "railway", "port", "airport"}
CN_LANDUSE = {"居住", "住宅", "商业", "工业", "农田", "耕地", "林地", "草地", "公园",
              "绿地", "水域", "仓储", "公共", "交通", "市政", "商住", "办公", "教育",
              "医疗", "耕地", "园地", "坑塘", "建设用地", "未利用地"}
ONEWAY_VALS = {"f", "t", "b", "1", "0", "是", "否", "单", "双", "单向", "双向",
               "true", "false", "yes", "no", "y", "n", "单行", "双行"}


# ---------------------------------------------------------------------------
# 文件探测
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    path: str
    kind: str                      # shp / csv / geojson
    geom: str                      # Point / Polyline / Polygon / None
    n_features: int
    columns: List[str]
    sample: Dict[str, List[str]]   # 每列的去重样例值（最多 12 个）
    card: Dict[str, int] = field(default_factory=dict)   # 每列实际不同取值个数（判断是否分类字段）
    crs: str = ""
    role: str = ""
    role_conf: float = 0.0
    role_reason: str = ""
    field_map: Dict[str, str] = field(default_factory=dict)
    field_conf: Dict[str, float] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": os.path.basename(self.path),
            "path": self.path,
            "kind": self.kind,
            "geom": self.geom,
            "n_features": self.n_features,
            "columns": self.columns,
            "sample": self.sample,
            "card": self.card,
            "crs": self.crs,
            "role": self.role,
            "role_label": ROLES.get(self.role, {}).get("label", "未识别"),
            "role_conf": round(self.role_conf, 3),
            "role_reason": self.role_reason,
            "field_map": self.field_map,
            "field_conf": {k: round(v, 3) for k, v in self.field_conf.items()},
            "error": self.error,
        }


_SHAPE_GEOM = {1: "Point", 3: "Polyline", 5: "Polygon", 8: "Point",
               11: "Point", 13: "Polyline", 15: "Polygon", 18: "Point",
               21: "Point", 23: "Polyline", 25: "Polygon", 28: "Point",
               31: "Polyline"}


def _dbf_meta(path: str, max_rows: int = 300) -> Tuple[List[str], Dict[str, List[str]], int, Dict[str, int]]:
    """只读 DBF 头与少量记录，不碰几何（155k 段路网也只花几十毫秒）。

    注意：DBF 每个字段的实际字节宽度写在字段描述符第 16 字节，不能假设固定宽度，
    否则记录会整段错位、取到的全是乱码。
    """
    with open(path, "rb") as f:
        head = f.read(32)
        if len(head) < 32:
            return [], {}, 0, {}
        n_rec = struct.unpack("<I", head[4:8])[0]
        head_len = struct.unpack("<H", head[8:10])[0]
        rec_len = struct.unpack("<H", head[10:12])[0]
        fields: List[str] = []
        widths: List[int] = []
        while True:
            b = f.read(32)
            if not b or len(b) < 32 or b[0] == 0x0D:
                break
            raw = b[:11].split(b"\x00")[0]
            try:
                nm = raw.decode("utf-8")
            except Exception:
                try:
                    nm = raw.decode("gbk")
                except Exception:
                    nm = raw.decode("latin-1")
            fields.append(nm.strip())
            widths.append(b[16] or 1)
        f.seek(head_len)
        block = f.read(rec_len * min(max_rows, n_rec))

    def dec(v: bytes) -> str:
        for enc in ("utf-8", "gbk"):
            try:
                return v.decode(enc).strip()
            except Exception:
                continue
        return v.decode("latin-1", errors="ignore").strip()

    samples: Dict[str, List[str]] = {c: [] for c in fields}
    seens: Dict[str, set] = {c: set() for c in fields}
    for r in range(min(max_rows, n_rec)):
        rec = block[r * rec_len:(r + 1) * rec_len]
        if len(rec) < rec_len:
            break
        pos = 1
        for c, w in zip(fields, widths):
            v = rec[pos:pos + w].split(b"\x00")[0]
            pos += w
            s = dec(v)
            if s:
                if len(seens[c]) < 5000:
                    seens[c].add(s)
                if s not in samples[c] and len(samples[c]) < 12:
                    samples[c].append(s)
    card = {c: len(seens[c]) for c in fields}
    return fields, samples, n_rec, card


def _shp_geom(path: str) -> Tuple[str, int]:
    with open(path, "rb") as f:
        head = f.read(100)
        if len(head) < 100:
            return "", 0
        st = struct.unpack("<i", head[32:36])[0]
        n_rec = struct.unpack(">i", head[24:28])[0]
    return _SHAPE_GEOM.get(st, ""), int(n_rec / 2)


def _prj_crs(path: str) -> str:
    p = os.path.splitext(path)[0] + ".prj"
    if not os.path.exists(p):
        return ""
    try:
        t = open(p, "r", encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""
    if "PROJCS" in t:
        return "投影坐标（米）"
    if "GEOGCS" in t:
        return "经纬度（WGS84 或相近）"
    return ""



def _inspect_vector_generic(path: str) -> FileInfo:
    """geojson / kml / gdb：先读成统一结构再取样。"""
    from .vec import gdb_layers, read_vector

    layer = None
    if path.lower().endswith(".gdb"):
        layers = gdb_layers(path)
        if not layers:
            return FileInfo(path=path, kind="gdb", geom="None", n_features=0,
                            columns=[], sample={}, error="无法列出 gdb 图层（需要 pyogrio）")
        layer = max(layers, key=lambda t: t[2])[0]
    sf = read_vector(path, layer=layer)
    cols = list(sf.attrs.keys())
    sample: Dict[str, List[str]] = {}
    card: Dict[str, int] = {}
    for c in cols:
        vals = [v for v in sf.attrs[c] if str(v).strip()]
        seen = list(dict.fromkeys(vals))
        sample[c] = seen[:12]
        card[c] = len(seen)
    geom = {"polygon": "Polygon", "polyline": "Polyline", "point": "Point"}.get(sf.kind, "")
    crs = "经纬度（WGS84）" if sf.geographic else "投影坐标（米）"
    fi = FileInfo(path=path, kind=os.path.splitext(path)[1].lstrip(".").lower(),
                  geom=geom, n_features=sf.n, columns=cols, sample=sample, card=card,
                  crs=crs)
    if layer:
        fi.path = path
        fi.crs = crs + "；图层 %s" % layer
    return fi


def _inspect_xlsx(path: str) -> FileInfo:
    from .vec import read_table

    cols, rows = read_table(path)
    sample: Dict[str, List[str]] = {}
    card: Dict[str, int] = {}
    for i, c in enumerate(cols):
        vals = [r[i] for r in rows[:400] if i < len(r) and r[i].strip()]
        seen = list(dict.fromkeys(vals))
        sample[c] = seen[:12]
        card[c] = len(seen)
    return FileInfo(path=path, kind="xlsx", geom="None", n_features=len(rows),
                    columns=cols, sample=sample, card=card, crs="")


def inspect_file(path: str) -> FileInfo:
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".geojson", ".json", ".kml") or path.lower().endswith(".gdb"):
            return _inspect_vector_generic(path)
        if ext in (".xlsx", ".xls"):
            return _inspect_xlsx(path)
        if ext == ".shp":
            geom, n = _shp_geom(path)
            dbf = os.path.splitext(path)[0] + ".dbf"
            cols, sample, n2, card = (_dbf_meta(dbf) if os.path.exists(dbf)
                                     else ([], {}, 0, {}))
            return FileInfo(path=path, kind="shp", geom=geom, n_features=n2 or n,
                            columns=cols, sample=sample, card=card, crs=_prj_crs(path))
        if ext in (".geojson", ".json"):
            with open(path, "r", encoding="utf-8") as fh:
                gj = json.load(fh)
            feats = gj.get("features", []) if isinstance(gj, dict) else []
            geom = ""
            cols: List[str] = []
            sample: Dict[str, List[str]] = {}
            for ft in feats[:400]:
                g = (ft.get("geometry") or {}).get("type", "")
                if not geom and g:
                    geom = {"Point": "Point", "MultiPoint": "Point",
                            "LineString": "Polyline", "MultiLineString": "Polyline",
                            "Polygon": "Polygon", "MultiPolygon": "Polygon"}.get(g, "")
                for k, v in (ft.get("properties") or {}).items():
                    if k not in cols:
                        cols.append(k)
                        sample[k] = []
                    s = str(v).strip() if v is not None else ""
                    if s and s not in sample[k] and len(sample[k]) < 12:
                        sample[k].append(s)
            return FileInfo(path=path, kind="geojson", geom=geom, n_features=len(feats),
                            columns=cols, sample=sample, crs="经纬度（GeoJSON 默认）")
        if ext == ".csv":
            raw = open(path, "rb").read(200000)
            text = None
            for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue
            text = text or raw.decode("latin-1", errors="ignore")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            if not lines:
                return FileInfo(path=path, kind="csv", geom="None", n_features=0,
                                columns=[], sample={}, error="文件为空")
            delim = ","
            for d in (",", ";", "\t", "|"):
                if lines[0].count(d) >= max(1, len(lines[0]) // 40):
                    delim = d
                    break
            rows = list(csv.reader(lines, delimiter=delim))
            cols = [c.strip() for c in rows[0]]
            sample = {c: [] for c in cols}
            seens = {c: set() for c in cols}
            for r in rows[1:401]:
                for i, c in enumerate(cols):
                    if i < len(r):
                        s = r[i].strip()
                        if s:
                            seens[c].add(s)
                            if s not in sample[c] and len(sample[c]) < 12:
                                sample[c].append(s)
            card = {c: len(seens[c]) for c in cols}
            return FileInfo(path=path, kind="csv", geom="None",
                            n_features=max(0, len(lines) - 1), columns=cols, sample=sample,
                            card=card, crs="")
    except Exception as exc:
        return FileInfo(path=path, kind=ext.lstrip("."), geom="None", n_features=0,
                        columns=[], sample={}, error=str(exc))
    return FileInfo(path=path, kind=ext.lstrip("."), geom="None", n_features=0,
                    columns=[], sample={}, error="不支持的文件类型")


# ---------------------------------------------------------------------------
# 字段语义打分
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return str(s).strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _name_score(col: str, role_field: str) -> float:
    n = _norm(col)
    best = 0.0
    for kw in SYN.get(role_field, []):
        k = _norm(kw)
        if not k:
            continue
        if n == k:
            best = max(best, 1.0)
        elif k in n or n in k:
            best = max(best, 0.75)
    return best


def _value_score(values: List[str], role_field: str) -> float:
    v = [str(x).strip() for x in values if str(x).strip()]
    if not v:
        return 0.0
    uniq = list(dict.fromkeys(v))
    n = len(uniq)
    low = {x.lower() for x in uniq}

    if role_field == "road_class":
        hit = len(low & OSM_ROAD)
        hit += sum(1 for x in uniq if x in CN_ROAD or any(k in x for k in CN_ROAD))
        return min(1.0, hit / max(1, min(n, 8)))

    if role_field == "oneway":
        return min(1.0, len(low & ONEWAY_VALS) / max(1, n)) if n <= 8 else 0.0

    if role_field in ("landuse", "landuse_class"):
        hit = len(low & OSM_LANDUSE)
        hit += sum(1 for x in uniq if any(k in x for k in CN_LANDUSE))
        return min(1.0, hit / max(1, min(n, 8)))

    if role_field == "district":
        cn = sum(1 for x in uniq if x.endswith(("区", "县", "市", "旗")))
        return min(1.0, cn / max(1, n))

    if role_field == "street":
        cn = sum(1 for x in uniq if x.endswith(("街道", "镇", "乡", "苏木")))
        return min(1.0, cn / max(1, n))

    if role_field in ("x", "y"):
        nums = 0
        for x in uniq[:8]:
            try:
                float(x)
                nums += 1
            except Exception:
                pass
        return 0.6 * (nums / max(1, len(uniq[:8])))

    if role_field in ("price", "unit_price"):
        nums = 0
        for x in uniq[:8]:
            try:
                if float(str(x).replace(",", "")) > 0:
                    nums += 1
            except Exception:
                pass
        base = 0.5 * (nums / max(1, len(uniq[:8])))
        if role_field == "unit_price" and nums:
            try:
                med = sorted(float(str(x).replace(",", "")) for x in uniq[:8] if
                             str(x).replace(",", "").replace(".", "").isdigit())
                if med and med[len(med) // 2] > 20000:
                    base += 0.3      # 单价常见量级 2 万以上
            except Exception:
                pass
        return min(1.0, base)

    if role_field == "date":
        hit = sum(1 for x in uniq if len(x) >= 8 and (x[4:5] in "-/年" or x[:4].isdigit()))
        return min(1.0, hit / max(1, n))

    if role_field == "name":
        if n < 3:
            return 0.0
        # 名称列应当是真名字（含汉字），而不是居委会代码这类纯数字
        cjk = sum(1 for x in uniq if any("\u4e00" <= ch <= "\u9fff" for ch in x))
        nonnum = sum(1 for x in uniq if not x.replace(".", "").isdigit())
        return 0.7 * (cjk / n) + 0.3 * (nonnum / n)

    if role_field == "category":
        return 0.5 if 2 <= n <= 40 else 0.1

    if role_field == "unit_id":
        return 0.5 if n >= 3 else 0.0

    return 0.0


def _assign_fields(fi: FileInfo, role: str) -> Tuple[Dict[str, str], Dict[str, float]]:
    """给一个文件里的每个必需字段挑一列，做一对一贪心分配。"""
    spec = ROLES[role]["fields"]
    cands = []
    for fld in spec:
        for col in fi.columns:
            ns = _name_score(col, fld)
            # 坐标类字段必须靠名字认：数值列太多（面积、楼层、总价都能是数字），
            # 只看取值会把“建筑面积”误判成 Y 坐标
            if fld in ("x", "y") and ns < 0.2:
                continue
            vals = fi.sample.get(col, [])
            s = 0.55 * ns + 0.45 * _value_score(vals, fld)
            if not vals:
                s *= 0.25          # 整列为空的字段不能用，即使名字再像
            # 名称字段应当接近全唯一；只有几个取值的（村委会/居委会分类）是分类字段
            if fld == "name":
                card = fi.card.get(col, len(vals))
                if card < 20 and fi.n_features > 200:
                    s *= 0.35
            if s > 0.12:
                cands.append((s, fld, col))
    cands.sort(reverse=True)
    used_cols, used_flds = set(), set()
    fmap, fconf = {}, {}
    for s, fld, col in cands:
        if fld in used_flds or col in used_cols:
            continue
        fmap[fld] = col
        fconf[fld] = s
        used_flds.add(fld)
        used_cols.add(col)
    return fmap, fconf


def _guess_role(fi: FileInfo) -> Tuple[str, float, str]:
    geom = fi.geom
    if geom == "None" or fi.kind == "csv":
        # 表格：有价格列就是成交表
        best_p = 0.0
        for col in fi.columns:
            best_p = max(best_p, _value_score(fi.sample.get(col, []), "price"),
                         _name_score(col, "price"))
        if best_p > 0.45:
            return "obs", min(1.0, 0.5 + best_p * 0.5), "含价格字段的表格"
        return "obs", 0.35, "表格文件（默认识别为成交表）"

    if geom == "Polygon":
        lu = max((_value_score(fi.sample.get(c, []), "landuse") for c in fi.columns), default=0)
        ds = max((_value_score(fi.sample.get(c, []), "district") for c in fi.columns), default=0)
        if ds >= lu and ds > 0.3:
            return "units", min(1.0, 0.55 + ds * 0.45), "面要素 + 含区县字段，判为评估单元边界"
        if lu > 0.3:
            return "landuse", min(1.0, 0.55 + lu * 0.45), "面要素 + 含用地类型，判为土地利用"
        return "units", 0.4, "面要素（无区县字段，需人工确认）"

    if geom == "Polyline":
        rc = max((_value_score(fi.sample.get(c, []), "road_class") for c in fi.columns), default=0)
        return "roads", min(1.0, 0.55 + rc * 0.45), "线要素，判为路网（等级字段置信度 %.0f%%）" % (rc * 100)

    if geom == "Point":
        return "poi", 0.7, "点要素，判为 POI"

    return "", 0.0, "未能识别"


def guess_roles(files: List[FileInfo]) -> List[FileInfo]:
    """给每个文件定角色、定字段；同类多文件时保留要素最多的那个。"""
    for fi in files:
        if fi.error:
            continue
        fi.role, fi.role_conf, fi.role_reason = _guess_role(fi)
        if fi.role:
            fi.field_map, fi.field_conf = _assign_fields(fi, fi.role)

    best: Dict[str, FileInfo] = {}
    for fi in files:
        if not fi.role or fi.error:
            continue
        cur = best.get(fi.role)
        if cur is None or fi.n_features > cur.n_features:
            best[fi.role] = fi
    for fi in files:
        if fi.role and not fi.error and best.get(fi.role) is not fi:
            fi.role_reason += "（同类文件较多，选用要素数最多的那个）"
    return files


# ---------------------------------------------------------------------------
# 生成数据源配置
# ---------------------------------------------------------------------------

def build_datasource(mapping: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """mapping: role -> {path, fields:{role_field: column}}"""
    ds: Dict[str, Any] = {"name": "用户上传数据"}

    def path_of(role):
        m = mapping.get(role) or {}
        p = (m.get("path") or "").strip()
        return p or ""

    def f_of(role, key, default=""):
        m = mapping.get(role) or {}
        return ((m.get("fields") or {}).get(key) or default)

    if path_of("units"):
        ds["village"] = path_of("units")
        ds["fields"] = ds.get("fields", {})
        ds["fields"]["village_district"] = f_of("units", "district", "区县")
        ds["fields"]["village_street"] = f_of("units", "street", "街道")
        ds["fields"]["village_name"] = f_of("units", "name", "名称")
    if path_of("roads"):
        ds["roads"] = path_of("roads")
        ds.setdefault("fields", {})
        ds["fields"]["road_class"] = f_of("roads", "road_class", "fclass")
        ds["fields"]["road_oneway"] = f_of("roads", "oneway", "oneway")
    if path_of("landuse"):
        ds["landuse"] = path_of("landuse")
        ds.setdefault("fields", {})
        ds["fields"]["landuse_class"] = f_of("landuse", "landuse_class", "fclass")
    if path_of("obs"):
        ds["obs"] = path_of("obs")
    # 未提供的置为非法路径，让 realdata 走降级逻辑
    ds.setdefault("village", ds.get("village", ""))
    ds.setdefault("roads", ds.get("roads", ""))
    ds.setdefault("landuse", ds.get("landuse", ""))
    ds.setdefault("poi_gdb", "")
    ds.setdefault("fields", {})
    return ds
