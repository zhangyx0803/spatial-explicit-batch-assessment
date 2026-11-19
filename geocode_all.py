# -*- coding: utf-8 -*-
"""批量地理编码：把小区价目表落到经纬度。

用法：
    set AMAP_KEY=xxx
    python geocode_all.py [--limit N] [--delay 0.36]

特性：
    · 断点续传（缓存 _geocode_cache.json）
    · 高德返回 GCJ-02，自动纠偏为 WGS84（与评估单元坐标系一致）
    · 配额耗尽自动停止，下次接着跑
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "data", "external")
SRC = os.path.join(EXT, "小区价目表_上海.csv")
CACHE = os.path.join(EXT, "_geocode_cache.json")
OUT = os.path.join(EXT, "community_xy.csv")

AMAP = "https://restapi.amap.com/v3/place/text"
UA = {"User-Agent": "seba-research"}

# ---------------- GCJ-02 → WGS84 ----------------
_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj2wgs(lon: float, lat: float):
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(rad) * math.pi)
    return lon - dlon, lat - dlat


def load_cache():
    if os.path.exists(CACHE):
        try:
            return json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c):
    json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def query(key, name, city, district):
    params = {
        "key": key, "keywords": name, "city": city, "citylimit": "true",
        "types": "120000|120300", "offset": 5, "page": 1, "output": "JSON",
    }
    url = AMAP + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("status") != "1":
        return {"_err": d.get("info", "?")}
    pois = d.get("pois") or []
    if not pois:
        return None
    best = None
    for p in pois:
        nm = p.get("name", "")
        ad = p.get("adname", "")
        loc = (p.get("location") or "").split(",")
        if len(loc) != 2:
            continue
        score = 0
        if nm == name:
            score += 3
        elif name in nm or nm in name:
            score += 2
        if district and ad == district:
            score += 2
        if best is None or score > best[0]:
            best = (score, nm, ad, float(loc[0]), float(loc[1]))
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.36)
    args = ap.parse_args()

    key = os.environ.get("AMAP_KEY", "").strip()
    if not key:
        print("请先设置 AMAP_KEY 环境变量")
        return 2
    if not os.path.exists(SRC):
        print("找不到", SRC)
        return 2

    rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
    cache = load_cache()
    todo = [r for r in rows if r["小区名"] not in cache]
    if args.limit:
        todo = todo[: args.limit]
    print("待编码 %d / 共 %d 条（已缓存 %d）" % (len(todo), len(rows), len(cache)), flush=True)

    ok = miss = 0
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        nm, d, pr = r["小区名"].strip(), r["区县"].strip(), r["挂牌单价"]
        try:
            res = query(key, nm, "上海", d)
        except Exception as exc:
            print("  [%d] %s 网络异常 %s，暂停 5s" % (i, nm, str(exc)[:40]), flush=True)
            time.sleep(5)
            continue
        if isinstance(res, dict) and res.get("_err"):
            err = res["_err"]
            print("  接口返回 %s，停止" % err, flush=True)
            if "OVER_LIMIT" in err or "QUOTA" in err.upper():
                break
            continue
        if res is None:
            cache[nm] = {"district": d, "price": pr, "hit": 0}
            miss += 1
        else:
            _, mname, ad, glon, glat = res
            lon, lat = gcj2wgs(glon, glat)
            cache[nm] = {"district": d, "price": pr, "hit": 1, "poi": mname,
                         "adname": ad, "lon": lon, "lat": lat}
            ok += 1
        if i % 50 == 0:
            save_cache(cache)
            el = time.time() - t0
            print("  %d/%d  命中 %d  未命中 %d  已用 %.0f 分钟"
                  % (i, len(todo), ok, miss, el / 60), flush=True)
        time.sleep(args.delay)

    save_cache(cache)

    # 导出
    out = []
    for nm, v in cache.items():
        if v.get("hit"):
            out.append([nm, v["district"], v["price"], "%.6f" % v["lon"],
                        "%.6f" % v["lat"], v.get("poi", ""), v.get("adname", "")])
    with open(OUT, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["小区名", "区县", "挂牌单价", "经度", "纬度", "高德POI", "高德区县"])
        w.writerows(out)
    print("\n完成：缓存 %d 条，其中有坐标 %d 条 → %s"
          % (len(cache), len(out), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
