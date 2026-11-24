# -*- coding: utf-8 -*-
"""小区名 -> 经纬度（高德开放平台 POI 搜索）。

为什么需要这一步：手工整理房价时最容易记的是小区名 + 单价，
最难弄的是经纬度。高德提供免费的地理编码/POI 检索接口，
个人开发者每天 5000 次，够采几千个小区。

准备：
  1. 注册 https://lbs.amap.com/ （免费）
  2. 控制台 -> 应用管理 -> 创建应用 -> 添加 Key -> 服务平台选Web服务
  3. 把 Key 填到下面的命令里

用法：
  set AMAP_KEY=你的key
  python geocode_communities.py 小区名表.csv --city 上海

输入 CSV 只需一列小区名（也可以有单价、区县等其他列，不影响）。
输出：在原表基础上补 lon / lat 两列，另存为新文件。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

AMAP_TEXT = "https://restapi.amap.com/v3/place/text"
CACHE_NAME = "_geocode_cache.json"

def load_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            return json.load(open(path, "r", encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(path: str, cache: dict) -> None:
    try:
        json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass

def search(key: str, name: str, city: str, citylimit: bool = True):
    """返回 (lon, lat, 匹配到的名称, 类型) 或 (None, None, '', '')"""
    q = {
        "key": key,
        "keywords": name,
        "city": city,
        "citylimit": "true" if citylimit else "false",
        "offset": 5,
        "page": 1,
        "extensions": "base",
    }
    url = AMAP_TEXT + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "SEBA-research/1.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read().decode("utf-8"))
    if str(data.get("status")) != "1":
        raise RuntimeError("高德返回错误：%s %s" % (data.get("infocode"), data.get("info")))
    pois = data.get("pois") or []
    if not pois:
        return None, None, "", ""
    # 优先住宅区类，否则取第一个
    best = None
    for p in pois:
        t = str(p.get("type") or "")
        if "住宅" in t or "小区" in t or "商务住宅" in t:
            best = p
            break
    if best is None:
        best = pois[0]
    loc = str(best.get("location") or "")
    if "," not in loc:
        return None, None, "", ""
    lon_s, lat_s = loc.split(",")[:2]
    return float(lon_s), float(lat_s), str(best.get("name") or ""), str(best.get("type") or "")

def read_csv(path: str):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue
    else:
        text = raw.decode("latin-1", errors="ignore")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    delim = ","
    for d in (",", ";", "\t"):
        if lines[0].count(d) >= 1:
            delim = d
            break
    import io

    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    return rows[0], rows[1:]

def pick(cols, cands):
    for c in cands:
        for i, col in enumerate(cols):
            if col.strip() == c:
                return i
    for c in cands:
        for i, col in enumerate(cols):
            if c in col.strip():
                return i
    return -1

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--city", default="上海")
    ap.add_argument("--key", default=os.environ.get("AMAP_KEY", ""))
    ap.add_argument("--delay", type=float, default=0.35, help="每次请求间隔秒数（礼貌限速）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=全部）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not args.key:
        print("=" * 66)
        print("  还没有高德 Key")
        print("=" * 66)
        print("""
  获取方式（免费，5 分钟）：
    1. 打开 https://lbs.amap.com/  注册并登录
    2. 控制台 -> 应用管理 -> 我的应用 -> 创建新应用
       （名称随便填，比如批量评估研究，类型选出行）
    3. 点添加 Key，服务平台必须选【Web服务】
    4. 复制那串 Key，然后运行：

         set AMAP_KEY=你的key
         python geocode_communities.py %s

  免费额度：个人开发者 5000 次/天，地理编码与 POI 搜索各 5000 次。
  采集 3000 个小区完全够用。
""" % os.path.basename(args.csv))
        return 2

    if not os.path.exists(args.csv):
        print("找不到文件：%s" % args.csv)
        return 2

    cols, rows = read_csv(args.csv)
    i_name = pick(cols, ["小区名", "小区", "名称", "楼盘", "项目", "name", "community"])
    i_lon = pick(cols, ["经度", "lon", "lng"])
    i_lat = pick(cols, ["纬度", "lat"])
    if i_name < 0:
        print("[错误] 找不到小区名列。当前列：%s" % cols)
        return 2

    print("=" * 66)
    print("  小区名 -> 经纬度    （高德 POI 检索）")
    print("=" * 66)
    print("  输入：%s（%d 行）" % (os.path.basename(args.csv), len(rows)))
    print("  城市：%s    限速：%.2fs/次" % (args.city, args.delay))
    if i_lon >= 0 and i_lat >= 0:
        print("  检测到已有坐标列，将跳过这些行")

    cache_path = os.path.join(os.path.dirname(os.path.abspath(args.csv)), CACHE_NAME)
    cache = load_cache(cache_path)

    out_rows = []
    hit = miss = skip = 0
    t0 = time.time()
    todo = rows if not args.limit else rows[: args.limit]

    print("\n  开始......\n")
    for n, r in enumerate(todo, 1):
        name = r[i_name].strip() if i_name < len(r) else ""
        if not name:
            out_rows.append(list(r) + ["", ""])
            continue

        if i_lon >= 0 and i_lat >= 0 and i_lon < len(r) and i_lat < len(r):
            if r[i_lon].strip() and r[i_lat].strip():
                out_rows.append(list(r))
                skip += 1
                continue

        if name in cache:
            lon, lat = cache[name]
            out_rows.append(list(r) + [lon, lat])
            hit += 1
            continue

        try:
            lon, lat, matched, typ = search(args.key, name, args.city)
        except Exception as exc:
            print("  [%3d] %-24s 请求失败：%s" % (n, name[:24], str(exc)[:50]))
            out_rows.append(list(r) + ["", ""])
            miss += 1
            time.sleep(1.5)
            continue

        if lon is None:
            out_rows.append(list(r) + ["", ""])
            miss += 1
            print("  [%3d] %-24s 未找到" % (n, name[:24]))
        else:
            cache[name] = [lon, lat]
            out_rows.append(list(r) + [lon, lat])
            hit += 1
            flag = "" if matched == name else "  -> 匹配为%s" % matched
            print("  [%3d] %-24s %.6f, %.6f%s" % (n, name[:24], lon, lat, flag))

        if n % 20 == 0:
            save_cache(cache_path, cache)
            rate = (time.time() - t0) / n
            left = (len(todo) - n) * rate
            print("      - 进度 %d/%d，已用 %.0fs，预计还需 %.0fs -"
                  % (n, len(todo), time.time() - t0, left))
        time.sleep(args.delay)

    save_cache(cache_path, cache)

    out = args.out or os.path.splitext(args.csv)[0] + "_含坐标.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols + ["经度", "纬度"])
        w.writerows(out_rows)

    total = len(todo)
    print("\n" + "=" * 66)
    print("  完成：成功 %d，未找到 %d，跳过 %d，共 %d 条，用时 %.0fs"
          % (hit, miss, skip, total, time.time() - t0))
    print("  输出：%s" % out)
    print("\n  下一步：")
    print("    python import_prices.py \"%s\" --district 徐汇区" % out)
    print("=" * 66)
    return 0

if __name__ == "__main__":
    sys.exit(main())
