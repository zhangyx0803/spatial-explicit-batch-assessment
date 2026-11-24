# -*- coding: utf-8 -*-
"""生成导入用的样例 CSV，放到样例数据目录。"""
import os
import numpy as np
import pandas as pd

rng = np.random.default_rng(7)
OUT = "样例数据"
os.makedirs(OUT, exist_ok=True)

# 研究区：上海市区一块 8km x 8km，格网 250m
N = 32
CELL = 250.0
LON0, LAT0 = 121.4000, 31.2000
DEG_X = 1.0 / (111320.0 * np.cos(np.radians(LAT0)))     # 每米经度
DEG_Y = 1.0 / 110540.0                                   # 每米纬度

rows = []
pop = np.exp(-(((np.arange(N)[:, None] - N * 0.45) / (N * 0.25)) ** 2
               + ((np.arange(N)[None, :] - N * 0.5) / (N * 0.28)) ** 2))
for i in range(N):
    for j in range(N):
        lon = LON0 + (i * CELL + CELL / 2) * DEG_X
        lat = LAT0 + (j * CELL + CELL / 2) * DEG_Y
        rows.append({
            "单元编号": "A%03d%03d" % (i + 1, j + 1),
            "经度": round(lon, 7),
            "纬度": round(lat, 7),
            "行政区": "P%02d" % (i // 8 * 4 + j // 8 + 1),
            "常住人口": int(pop[i, j] * 4200 + rng.uniform(80, 300)),
        })
units = pd.DataFrame(rows)
units.to_csv(os.path.join(OUT, "1_评估单元.csv"), index=False, encoding="utf-8-sig")

# 成交：55% 单元有成交，单价随"越靠中心越贵"变化
cx, cy = N * 0.45, N * 0.5
rec = []
for _, r in units.iterrows():
    if rng.random() > 0.55:
        continue
    i = int(r["单元编号"][1:4]) - 1
    j = int(r["单元编号"][4:7]) - 1
    d = np.hypot((i - cx) / N, (j - cy) / N)
    price = 62000 * np.exp(-1.9 * d) * np.exp(rng.normal(0, 0.16))
    rec.append({
        "单元编号": r["单元编号"],
        "成交单价": int(round(price)),
        "成交日期": "%d-%02d-15" % (rng.choice([2023, 2024, 2025]), rng.integers(1, 13)),
    })
pd.DataFrame(rec).to_csv(os.path.join(OUT, "2_成交记录.csv"), index=False, encoding="utf-8-sig")

# 路网：格网边清单
edges = []
for i in range(N):
    for j in range(N):
        lon = LON0 + (i * CELL + CELL / 2) * DEG_X
        lat = LAT0 + (j * CELL + CELL / 2) * DEG_Y
        if i + 1 < N:
            edges.append({
                "起点经度": round(lon, 7), "起点纬度": round(lat, 7),
                "终点经度": round(lon + CELL * DEG_X, 7), "终点纬度": round(lat, 7),
                "道路等级": 1 if j % 4 == 0 else 3, "是否单向": 0,
            })
        if j + 1 < N:
            edges.append({
                "起点经度": round(lon, 7), "起点纬度": round(lat, 7),
                "终点经度": round(lon, 7), "终点纬度": round(lat + CELL * DEG_Y, 7),
                "道路等级": 1 if i % 4 == 0 else 3, "是否单向": 0,
            })
pd.DataFrame(edges).to_csv(os.path.join(OUT, "3_道路网.csv"), index=False, encoding="utf-8-sig")

# 设施：学校 + 地铁站
sch = []
for k in range(14):
    lon = LON0 + rng.uniform(0, N) * CELL * DEG_X
    lat = LAT0 + rng.uniform(0, N) * CELL * DEG_Y
    sch.append({"名称": "学校%02d" % (k + 1), "经度": round(lon, 7), "纬度": round(lat, 7),
                "班数": int(rng.integers(12, 40))})
pd.DataFrame(sch).to_csv(os.path.join(OUT, "4_学校.csv"), index=False, encoding="utf-8-sig")

met = []
for k, (a, b) in enumerate([(5, 6), (14, 9), (24, 14), (9, 22), (20, 25)]):
    met.append({"名称": "地铁站%02d" % (k + 1),
                "经度": round(LON0 + (a * CELL + CELL / 2) * DEG_X, 7),
                "纬度": round(LAT0 + (b * CELL + CELL / 2) * DEG_Y, 7)})
pd.DataFrame(met).to_csv(os.path.join(OUT, "5_地铁站.csv"), index=False, encoding="utf-8-sig")

print("已生成：")
for f in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, f)
    print("  %-16s %6.1f KB" % (f, os.path.getsize(p) / 1024))
print("评估单元 %d 行 / 成交 %d 行 / 路网 %d 条 / 学校 %d / 地铁 %d"
      % (len(units), len(rec), len(edges), len(sch), len(met)))
