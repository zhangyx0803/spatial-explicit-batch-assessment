# -*- coding: utf-8 -*-
"""验证识别引擎：真实文件 + 改名后的文件都要能认出来。"""
import sys

sys.path.insert(0, ".")
from seba.intake import FileInfo, _assign_fields, _guess_role, guess_roles, inspect_file

DATA = r"F:\上海师大\各种地理数据"
P_VILLAGE = DATA + r"\2024全国村级行政边界\1上海村社区界\上海村界.shp"
P_ROADS = DATA + r"\2024年道路数据（全国、分省、分城市）\分城市的道路数据\【立方数据学社】上海市\上海市.shp"
P_LANDUSE = DATA + r"\2026省级土地利用\各省土地利用矢量2026shp\上海市土地利用2026.shp"

print("=" * 78)
print("A. 真实文件探测")
print("=" * 78)
for p in (P_VILLAGE, P_ROADS, P_LANDUSE):
    fi = inspect_file(p)
    print("\n%-14s %s" % (fi.kind, fi.path.split("\\")[-1]))
    print("   几何=%s  要素=%d  CRS=%s" % (fi.geom, fi.n_features, fi.crs))
    print("   字段(%d): %s" % (len(fi.columns), fi.columns[:9]))
    r, c, why = _guess_role(fi)
    print("   → 识别为 %s（置信 %.0f%%）：%s" % (r, c * 100, why))
    fm, fc = _assign_fields(fi, r)
    print("   字段映射: %s" % {k: (v, round(fc[k], 2)) for k, v in fm.items()})

print()
print("=" * 78)
print("B. 换一套字段名（模拟用户自己整理的数据，完全没有 fclass）")
print("=" * 78)

cases = [
    ("路网-中文列名", "Polyline", ["ID", "道路等级", "通行方向", "路名", "长度"],
     {"道路等级": ["主干路", "次干路", "支路", "快速路", "高速"],
      "通行方向": ["单向", "双向"], "路名": ["中山路", "漕溪北路"], "长度": ["123.4"]}),
    ("路网-英文列名", "Polyline", ["gid", "ROAD_TYPE", "ONEWAY", "NAME"],
     {"ROAD_TYPE": ["motorway", "primary", "secondary", "residential"],
      "ONEWAY": ["F", "T", "B"], "NAME": ["A St"]}),
    ("路网-无意义列名", "Polyline", ["FIELD_1", "FIELD_2", "FIELD_3"],
     {"FIELD_2": ["motorway", "trunk", "primary", "secondary", "tertiary", "service"],
      "FIELD_3": ["F", "T", "B"]}),
    ("土地利用-中文", "Polygon", ["OBJECTID", "用地性质", "面积"],
     {"用地性质": ["居住用地", "商业用地", "工业用地", "林地", "耕地", "公园绿地"]}),
    ("评估单元-中文", "Polygon", ["BSM", "所属区县", "所属街道", "村居名称"],
     {"所属区县": ["徐汇区", "静安区", "黄浦区"], "所属街道": ["田林街道", "江宁路街道"],
      "村居名称": ["威海居委"]}),
    ("评估单元-英文", "Polygon", ["OID", "COUNTY", "TOWNSHIP", "VILLAGE"],
     {"COUNTY": ["A区", "B区"], "TOWNSHIP": ["甲镇", "乙镇"], "VILLAGE": ["v1"]}),
    ("成交表-中文", "None", ["单元编号", "成交总价", "成交单价", "签约日期", "建筑面积"],
     {"成交总价": ["5800000", "7200000"], "成交单价": ["64500", "80200"],
      "签约日期": ["2024-06-15"], "单元编号": ["V00001"], "建筑面积": ["90"]}),
    ("成交表-英文", "None", ["unit_id", "price", "unit_price", "deal_date"],
     {"price": ["5800000"], "unit_price": ["64500"], "deal_date": ["2024-06-15"]}),
    ("POI-中文", "Point", ["NAME", "设施类型", "地址"],
     {"设施类型": ["商场", "超市", "便利店", "餐饮"], "NAME": ["某商场"]}),
]

ok = 0
for label, geom, cols, sample in cases:
    fi = FileInfo(path="/x/%s.shp" % label, kind="shp" if geom != "None" else "csv",
                  geom=geom, n_features=1000, columns=cols, sample=sample)
    r, c, why = _guess_role(fi)
    fm, fc = _assign_fields(fi, r) if r else ({}, {})
    want = {"路网": "roads", "土地利用": "landuse", "评估单元": "units",
            "成交表": "obs", "POI": "poi"}[label.split("-")[0]]
    hit = r == want
    ok += hit
    print("\n%s %s" % ("✅" if hit else "❌", label))
    print("   识别为 %s（%.0f%%）" % (r, c * 100))
    print("   映射: %s" % {k: v for k, v in fm.items()})

print("\n" + "=" * 78)
print("识别正确 %d / %d" % (ok, len(cases)))
