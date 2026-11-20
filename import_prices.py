# -*- coding: utf-8 -*-
"""把“小区价目表”转换成系统能吃的“成交记录”，自动落位到评估单元。

适用场景：你从任何合规渠道拿到一张小区价格表（手工整理、官方公示、
机构授权数据），都能用它接进模型。

输入 CSV 至少要有“单价”一列，另外提供以下任一空间信息：
    经度 + 纬度      → 按最近邻落到评估单元（推荐）
    所属街道         → 落到该街道内所有单元（较粗，但可用）

用法：
    python import_prices.py 小区价目表.csv --district 徐汇区
    python import_prices.py 小区价目表.csv --district 奉贤区 --out 成交记录.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

HERE = os.path.dirname(os.path.abspath(__file__))

# 价格合理性区间（元/㎡），超出视为录入错误
PRICE_RANGE = (3000, 300000)


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


def pick_col(cols, cands):
    for c in cands:
        for i, col in enumerate(cols):
            if col.strip().lower() == c.lower():
                return i
    for c in cands:
        for i, col in enumerate(cols):
            if c.lower() in col.strip().lower():
                return i
    return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--district", default="徐汇区")
    ap.add_argument("--out", default="")
    ap.add_argument("--bundle", default="", help="用预打包数据集里的评估单元（无需原始地理数据）")
    ap.add_argument("--snap-m", type=float, default=1500.0,
                    help="小区点到评估单元中心的最大距离（米），超过则丢弃")
    ap.add_argument("--agg", default="median", choices=["median", "mean"],
                    help="一个单元有多个小区时的汇总方式")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print("找不到文件：%s" % args.csv)
        return 2

    print("=" * 66)
    print("  小区价目表 → 评估单元")
    print("=" * 66)

    cols, rows = read_csv(args.csv)
    print("\n[1] 读取 %s" % os.path.basename(args.csv))
    print("    列：%s" % " | ".join(cols))
    print("    行数：%d" % len(rows))

    i_name = pick_col(cols, ["小区名", "小区", "楼盘", "项目", "名称", "name", "community"])
    i_price = pick_col(cols, ["单价", "成交单价", "均价", "挂牌均价", "unit_price",
                              "price_pm2", "元/平", "价格"])
    i_lon = pick_col(cols, ["经度", "lon", "lng", "longitude", "x"])
    i_lat = pick_col(cols, ["纬度", "lat", "latitude", "y"])
    i_street = pick_col(cols, ["街道", "所属街道", "板块", "所属街", "street", "town"])

    if i_price < 0:
        print("\n[错误] 找不到单价列。需要的列名可以是：单价 / 成交单价 / 均价 / unit_price")
        return 2
    has_xy = i_lon >= 0 and i_lat >= 0
    has_street = i_street >= 0
    if not has_xy and not has_street:
        print("\n[错误] 既没有经纬度也没有街道列，无法落位。")
        print("       请至少提供：经度+纬度，或者 所属街道")
        return 2

    print("\n[2] 字段识别")
    print("    名称  : %s" % (cols[i_name] if i_name >= 0 else "（无）"))
    print("    单价  : %s" % cols[i_price])
    print("    坐标  : %s" % ("%s, %s" % (cols[i_lon], cols[i_lat]) if has_xy else "（无）"))
    print("    街道  : %s" % (cols[i_street] if has_street else "（无）"))

    # ---- 解析并校验 ----
    recs = []
    bad_price = bad_coord = 0
    for r in rows:
        try:
            p = float(str(r[i_price]).replace(",", "").replace("元/㎡", "")
                      .replace("元/m2", "").replace("元/平", "").strip())
        except Exception:
            bad_price += 1
            continue
        if not (PRICE_RANGE[0] <= p <= PRICE_RANGE[1]):
            bad_price += 1
            continue
        item = {"name": r[i_name].strip() if i_name >= 0 else "",
                "price": p,
                "street": r[i_street].strip() if has_street else ""}
        if has_xy:
            try:
                item["lon"] = float(r[i_lon])
                item["lat"] = float(r[i_lat])
            except Exception:
                bad_coord += 1
                continue
        recs.append(item)

    print("\n[3] 数据校验")
    print("    有效记录：%d" % len(recs))
    if bad_price:
        print("    丢弃（单价格式/范围异常）：%d  （合理区间 %.0f–%.0f 元/㎡）"
              % (bad_price, PRICE_RANGE[0], PRICE_RANGE[1]))
    if bad_coord:
        print("    丢弃（坐标无法解析）：%d" % bad_coord)
    if not recs:
        print("\n[错误] 没有有效记录。")
        return 2

    prices = sorted(x["price"] for x in recs)
    print("    单价中位 %.0f，P10 %.0f，P90 %.0f 元/㎡"
          % (prices[len(prices) // 2], prices[int(len(prices) * .1)],
             prices[int(len(prices) * .9)]))

    # ---- 落位 ----
    print("\n[4] 落位到评估单元（%s）" % args.district)

    import numpy as np

    bundle_path = args.bundle
    if not bundle_path:
        guess = os.path.join(HERE, "data", "demo_%s.bundle" % (
            {"徐汇区": "xuhui"}.get(args.district, "")))
        if os.path.exists(guess):
            bundle_path = guess

    if bundle_path and os.path.exists(bundle_path):
        from seba.bundle import load_bundle

        ds, _n, _e = load_bundle(bundle_path)
        print("    数据源：%s（预打包）" % os.path.basename(bundle_path))
    else:
        from seba.realdata import build_district_dataset

        ds, rep = build_district_dataset(args.district)
    units = ds.units
    n = ds.n_units
    print("    评估单元：%d 个（%s）" % (n, args.district))

    import numpy as np

    assign = np.full(n, np.nan)
    assign_cnt = np.zeros(n, dtype=int)
    buckets = [[] for _ in range(n)]

    if has_xy:
        # 经纬度 → 本地平面坐标（与 realdata 一致）
        lat0 = float(np.mean(units.y) * 0 + 31.2)
        lon0 = 121.4
        # 用单元坐标反推原点的经纬度基准
        from seba.realdata import SOURCE
        lat0, lon0 = 31.2, 121.4
        kx = 111320.0 * np.cos(np.radians(lat0))
        ky = 110540.0
        ux, uy = units.x, units.y
        dropped = 0
        for it in recs:
            x = (it["lon"] - lon0) * kx
            y = (it["lat"] - lat0) * ky
            d2 = (ux - x) ** 2 + (uy - y) ** 2
            j = int(np.argmin(d2))
            if d2[j] > args.snap_m ** 2:
                dropped += 1
                continue
            buckets[j].append(it["price"])
        if dropped:
            print("    超出 %.0f m 吸附范围而丢弃：%d 条" % (args.snap_m, dropped))
    else:
        streets = list(units.admin_code) if units.admin_code is not None else []
        by_street = {}
        for k, st in enumerate(streets):
            by_street.setdefault(str(st), []).append(k)
        hit = miss = 0
        for it in recs:
            idxs = by_street.get(it["street"])
            if not idxs:
                miss += 1
                continue
            hit += 1
            for k in idxs:
                buckets[k].append(it["price"])
        print("    按街道落位：命中 %d 条，街道名不匹配 %d 条" % (hit, miss))

    agg = np.median if args.agg == "median" else np.mean
    for k in range(n):
        if buckets[k]:
            assign[k] = float(agg(buckets[k]))
            assign_cnt[k] = len(buckets[k])

    covered = int(np.isfinite(assign).sum())
    print("    覆盖单元：%d / %d（%.0f%%）" % (covered, n, covered / n * 100))
    print("    单元内小区数中位：%d" % int(np.median(assign_cnt[assign_cnt > 0]))
          if covered else "    无覆盖")

    # ---- 输出 ----
    out = args.out or os.path.join(HERE, "dist_prices",
                                   "%s_成交记录.csv" % args.district)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单元编号", "成交单价", "成交日期"])
        for k in range(n):
            if np.isfinite(assign[k]):
                w.writerow([units.unit_id[k], "%.0f" % assign[k], "2024-11-20"])

    print("\n[5] 已输出：%s" % out)
    print("    %d 条记录，可直接用于建模（替换现有合成成交数据）" % covered)
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
