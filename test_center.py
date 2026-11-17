# -*- coding: utf-8 -*-
"""测试中心地识别：看识别出来的中心地像不像上海真实的商业中心。"""
import sys
import time

sys.path.insert(0, "vendor")
sys.path.insert(0, ".")
import numpy as np

from seba.centralplace import detect_centers
from seba.realdata import RAIL_EXCLUDE, load_osm_points

t = time.perf_counter()
sx, sy, sname, scls = load_osm_points("gis_osm_pois_free", keep=None)
print("全量 POI:", len(sx), "用时 %.1fs" % (time.perf_counter() - t))

# 只要商业类
from seba.realdata import SHOP_CLS
m = np.array([c in SHOP_CLS for c in scls])
print("商业 POI:", int(m.sum()))
shop_x, shop_y, shop_cls = sx[m], sy[m], scls[m]

# 参照点：地铁站名
lat0 = 31.2
kx = 111320.0 * np.cos(np.radians(lat0))
ky = 110540.0
lon0, lat0_ = 121.4, 31.2
mlon, mlat, mname, _ = load_osm_points("gis_osm_transport_free", keep={"railway_station"},
                                       exclude_names=RAIL_EXCLUDE)
names = [((mlon[i] - lon0) * kx, (mlat[i] - lat0_) * ky, str(mname[i])) for i in range(len(mlon))]

# 交通枢纽：机场与火车站，其内部零售不算中心地
hub_lon, hub_lat, hub_name, hub_fc = load_osm_points("gis_osm_transport_free", keep={"airport", "railway_station"})
hubs = []
for i in range(len(hub_lon)):
    if hub_fc[i] == "airport" or any(k in str(hub_name[i]) for k in ("火车站", "虹桥站", "上海站", "南站", "西站")):
        hubs.append(((hub_lon[i]-lon0)*kx, (hub_lat[i]-lat0_)*ky, 1500.0))
print("排除交通枢纽:", [(round(h[0]/1000), round(h[1]/1000)) for h in hubs])

px = (shop_x - lon0) * kx
py = (shop_y - lat0_) * ky

t = time.perf_counter()
cf = detect_centers(px, py, shop_cls, names=names, bandwidth_m=1500.0, nms_m=1200.0, min_poi_1km=10, exclude_xy=hubs)
print("识别用时 %.1fs" % (time.perf_counter() - t))
print("\n统计:", cf.stats)

for lvl in (1, 2, 3):
    lst = sorted(cf.by_level()[lvl], key=lambda c: -c.score)
    print("\n=== %d 级中心地 %d 个（前 15）===" % (lvl, len(lst)))
    for c in lst[:15]:
        print("  %-12s 强度 %8.1f  500m 商业 %3d  (%.0f, %.0f)"
              % (c.name or "—", c.score, c.n_poi, c.x / 1000, c.y / 1000))
