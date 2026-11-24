# -*- coding: utf-8 -*-
"""全市真实路网 + scipy 加速性能测试。"""
import math
import sys
import time

import numpy as np

sys.path.insert(0, "vendor")        # vendor 优先：保证 numpy 与 scipy 版本配套
sys.path.insert(0, ".")

from seba.net import CSRGraph, HAS_SCIPY, snap_points

SHP = r"F:\上海师大\各种地理数据\2024年道路数据（全国、分省、分城市）\分城市的道路数据\【立方数据学社】上海市\上海市.shp"

print("scipy 可用:", HAS_SCIPY)

import struct

def read_polylines(path):
    segs = []
    with open(path, "rb") as f:
        f.seek(100)
        while True:
            b = f.read(8)
            if len(b) < 8:
                break
            clen = struct.unpack(">i", b[4:8])[0] * 2
            body = f.read(clen)
            if len(body) < clen:
                break
            nparts = struct.unpack("<i", body[36:40])[0]
            npoints = struct.unpack("<i", body[40:44])[0]
            parts = np.frombuffer(body[44:44 + 4 * nparts], dtype="<i4")
            pts = np.frombuffer(body[44 + 4 * nparts:44 + 4 * nparts + 16 * npoints],
                                dtype="<f8").reshape(npoints, 2)
            bd = list(parts) + [npoints]
            for k in range(nparts):
                s = pts[bd[k]:bd[k + 1]]
                if s.shape[0] >= 2:
                    segs.append(s)
    return segs

LAT0, LON0 = 31.2, 121.4
KX = 111320.0 * math.cos(math.radians(LAT0))
KY = 110540.0

t = time.perf_counter()
segs = read_polylines(SHP)
print("读取 %d 段，%.1fs" % (len(segs), time.perf_counter() - t))

t = time.perf_counter()
key, nodes, edges = {}, [], []
TOL = 8.0

def nid(x, y):
    gx, gy = int(round(x / TOL)), int(round(y / TOL))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            j = key.get((gx + dx, gy + dy))
            if j is not None:
                px, py = nodes[j]
                if abs(px - x) <= TOL and abs(py - y) <= TOL:
                    return j
    j = len(nodes)
    key[(gx, gy)] = j
    nodes.append((x, y))
    return j

for seg in segs:
    x = (seg[:, 0] - LON0) * KX
    y = (seg[:, 1] - LAT0) * KY
    for k in range(len(x) - 1):
        L = math.hypot(x[k] - x[k + 1], y[k] - y[k + 1])
        if L <= 0.5:
            continue
        edges.append((nid(x[k], y[k]), nid(x[k + 1], y[k + 1]), L, 3, 0))
xy = np.array(nodes, dtype=float)
e = np.array(edges, dtype=float)
print("拓扑清洗 %.1fs：%d 节点 / %d 边" % (time.perf_counter() - t, xy.shape[0], e.shape[0]))

t = time.perf_counter()
g = CSRGraph(xy.shape[0], e, xy)
w = g.weights("drive")
print("建 CSR 图 %.1fs：%d 有向边" % (time.perf_counter() - t, g.n_edges))

# 起点：度数最大的节点
deg = np.diff(g.indptr) + np.diff(g.in_indptr)
src = int(np.argmax(deg))

print("\n单源最短路：")
t = time.perf_counter(); d1 = g.dijkstra(src, w); t_py = time.perf_counter() - t
print("  纯 Python  %.2fs（可达 %d）" % (t_py, int(np.isfinite(d1).sum())))
if HAS_SCIPY:
    t = time.perf_counter(); d2 = g.dijkstra_fast(src, w); t_sc = time.perf_counter() - t
    print("  scipy C    %.3fs（可达 %d）  加速 %.0f 倍" % (t_sc, int(np.isfinite(d2).sum()), t_py / max(t_sc, 1e-6)))
    print("  结果一致:", bool(np.allclose(np.where(np.isfinite(d1), d1, -1), np.where(np.isfinite(d2), d2, -1), atol=1e-6)))

print("\n多源批量（模拟设施做 2SFCA，流式不存全矩阵）：")
for N in (200, 500):
    rng = np.random.default_rng(0)
    srcs = rng.choice(g.n_nodes, N, replace=False)
    t = time.perf_counter()
    acc = np.zeros(g.n_nodes)
    peak = 0
    for (a, b), buf in g.iter_dijkstra_many(srcs, w, limit=30.0, chunk=32):
        peak = max(peak, buf.nbytes)
        acc += np.where(np.isfinite(buf), 1.0, 0.0).sum(axis=0)
    el = time.perf_counter() - t
    print("  %4d 个源 x %d 节点 -> %6.2fs（单批内存 %.0f MB），平均每个源 %.1f ms"
          % (N, g.n_nodes, el, peak / 1e6, el / N * 1000))

print("\n吸附（全市 500 m 格网）：")
ext_x = xy[:, 0].max() - xy[:, 0].min()
ext_y = xy[:, 1].max() - xy[:, 1].min()
NX = int(ext_x / 500); NY = int(ext_y / 500)
gx, gy = np.meshgrid((np.arange(NX) + .5) * 500, (np.arange(NY) + .5) * 500)
t = time.perf_counter()
s = snap_points(gx.ravel(), gy.ravel(), xy, 300.0)
print("  %d 个点 -> %.2fs，失败率 %.1f%%（矩形外接范围含大量非城区）"
      % (gx.size, time.perf_counter() - t, s.failed_share * 100))
print("\n全市 500m 格网单元数: %d；250m: %d" % (gx.size, gx.size * 4))
