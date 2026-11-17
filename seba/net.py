# -*- coding: utf-8 -*-
"""路网：CSR 稀疏图、阻抗加权 Dijkstra、起终点吸附。

按《实现方案》的选型，图结构、阻抗加权与 Dijkstra 全部自建（scipy.sparse + 堆），
不调用 osmnx 的图算法，只把 osmnx 当作数据下载器使用。

提供两条求解路径：
  dijkstra()                —— 节点图上的标准有界 Dijkstra（批量计算用，最快）
  dijkstra_edge_expanded()  —— 边扩展图上的 Dijkstra，支持转向惩罚与禁左（精确计算用）
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

__all__ = ["CSRGraph", "SnapResult", "snap_points", "SPEED_TABLE", "HAS_SCIPY"]

# scipy 为可选加速项：装了就走 C 实现（批量最短路快约两个数量级），没装自动回落到纯 Python
try:  # pragma: no cover
    from scipy.sparse import csr_matrix as _csr_matrix
    from scipy.sparse.csgraph import dijkstra as _scipy_dijkstra

    HAS_SCIPY = True
except Exception:  # pragma: no cover
    _csr_matrix = None
    _scipy_dijkstra = None
    HAS_SCIPY = False

# 道路等级 → 各模式速度（m/min）
SPEED_TABLE: Dict[str, Dict[int, float]] = {
    # 1 主干道 2 次干道 3 支路
    "drive": {1: 1000.0, 2: 666.7, 3: 416.7},   # 60 / 40 / 25 km/h
    "bike": {1: 250.0, 2: 250.0, 3: 250.0},     # 15 km/h
    "walk": {1: 80.0, 2: 80.0, 3: 80.0},        # 4.8 km/h
}


class CSRGraph:
    """有向图（双向边在建图时展开为两条），压缩稀疏行存储。"""

    def __init__(self, n_nodes: int, edges: np.ndarray, node_xy: np.ndarray):
        self.n_nodes = int(n_nodes)
        self.node_xy = np.asarray(node_xy, dtype=float)

        e = np.asarray(edges, dtype=float)
        if e.ndim != 2 or e.shape[1] != 5:
            raise ValueError("edges 必须是 (m, 5)：u, v, length, speed_class, oneway")
        u = e[:, 0].astype(np.int64)
        v = e[:, 1].astype(np.int64)
        length = e[:, 2]
        speed_class = e[:, 3].astype(np.int64)
        oneway = e[:, 4].astype(np.int64) != 0

        # 双向边展开
        fwd = np.column_stack([u, v, length, speed_class])
        rev_mask = ~oneway
        rev = np.column_stack([v[rev_mask], u[rev_mask], length[rev_mask], speed_class[rev_mask]])
        all_edges = np.vstack([fwd, rev])

        order = np.argsort(all_edges[:, 0], kind="stable")
        all_edges = all_edges[order]

        self.edge_src = all_edges[:, 0].astype(np.int64)
        self.edge_dst = all_edges[:, 1].astype(np.int64)
        self.edge_len = all_edges[:, 2].astype(float)
        self.edge_cls = all_edges[:, 3].astype(np.int64)

        counts = np.bincount(self.edge_src, minlength=self.n_nodes)
        self.indptr = np.zeros(self.n_nodes + 1, dtype=np.int64)
        np.cumsum(counts, out=self.indptr[1:])
        self.n_edges = int(self.edge_len.shape[0])
        # 边已按起点排序，于是"第 k 条入弧"就是第 k 号边本身
        self.indices = np.arange(self.n_edges, dtype=np.int64)
        self.oneway_share = float(oneway.mean()) if oneway.size else 0.0

        # 反向索引：节点 → 入边（边扩展图用）
        in_counts = np.bincount(self.edge_dst, minlength=self.n_nodes)
        self.in_indptr = np.zeros(self.n_nodes + 1, dtype=np.int64)
        np.cumsum(in_counts, out=self.in_indptr[1:])
        order_in = np.argsort(self.edge_dst, kind="stable")
        self.in_edges = order_in.astype(np.int64)

        # 每条边的方位角（解析转向关系用）
        p0 = self.node_xy[self.edge_src]
        p1 = self.node_xy[self.edge_dst]
        self.edge_bearing = np.arctan2(p1[:, 1] - p0[:, 1], p1[:, 0] - p0[:, 0])

    # ---- 阻抗 ----
    def weights(self, mode: str) -> np.ndarray:
        """边权（分钟）：长度 / 该等级该模式的行驶速度。"""
        if mode not in SPEED_TABLE:
            raise ValueError("未知出行模式：%s" % mode)
        table = SPEED_TABLE[mode]
        speed = np.array([table.get(int(c), min(table.values())) for c in self.edge_cls])
        return self.edge_len / speed

    # ---- 诊断 ----
    def connectivity(self) -> Dict[str, float]:
        """连通分量与悬挂节点统计，进质量报告。"""
        n = self.n_nodes
        adj: Dict[int, list] = {i: [] for i in range(n)}
        for k in range(self.n_edges):
            adj[int(self.edge_src[k])].append(int(self.edge_dst[k]))
        seen = np.zeros(n, dtype=bool)
        comps = []
        for s in range(n):
            if seen[s]:
                continue
            stack = [s]
            seen[s] = True
            size = 0
            while stack:
                cur = stack.pop()
                size += 1
                for nb in adj[cur]:
                    if not seen[nb]:
                        seen[nb] = True
                        stack.append(nb)
            comps.append(size)
        comps.sort(reverse=True)
        deg_sum = np.diff(self.indptr) + np.diff(self.in_indptr)
        dead = int((deg_sum == 1).sum())
        return {
            "n_components": float(len(comps)),
            "largest_component_share": float(comps[0] / n) if comps else 0.0,
            "n_deadend_nodes": float(dead),
            "deadend_ratio": float(dead / n) if n else 0.0,
            "oneway_share": self.oneway_share,
        }

    # ---- 单源最短路 ----
    def to_csr(self, w: np.ndarray):
        """转成 scipy 的 CSR 矩阵（只在装了 scipy 时可用）。

        CSR 的 indices 必须是**列号**，也就是每条边的终点节点；传边号会构造出错误的矩阵。
        """
        if not HAS_SCIPY:
            raise RuntimeError("未安装 scipy")
        return _csr_matrix(
            (np.asarray(w, dtype=float), self.edge_dst.astype(np.int32), self.indptr),
            shape=(self.n_nodes, self.n_nodes),
        )

    def iter_dijkstra_many(
        self,
        sources: np.ndarray,
        w: np.ndarray,
        limit: float = float("inf"),
        chunk: int = 32,
    ):
        """流式多源最短路：逐批产出 (起止下标, 该批的 (chunk, n_nodes) 距离矩阵)。

        必须流式：2000 个设施 × 70 万节点全量存下来要 11 GB，会直接 OOM。
        """
        sources = np.asarray(sources, dtype=np.int64)
        if not HAS_SCIPY:
            for a in range(0, sources.size, chunk):
                b = min(a + chunk, sources.size)
                buf = np.empty((b - a, self.n_nodes), dtype=float)
                for i, s in enumerate(sources[a:b]):
                    buf[i] = self.dijkstra(int(s), w, limit)
                yield (a, b), buf
            return

        g = self.to_csr(w)
        for a in range(0, sources.size, chunk):
            b = min(a + chunk, sources.size)
            yield (a, b), _scipy_dijkstra(g, directed=True, indices=sources[a:b],
                                          limit=limit, min_only=False)

    def dijkstra_many(
        self,
        sources: np.ndarray,
        w: np.ndarray,
        limit: float = float("inf"),
        chunk: int = 64,
    ) -> np.ndarray:
        """多源批量最短路，返回 (len(sources), n_nodes)。

        只在源数量较少时使用；大规模请用 iter_dijkstra_many 流式处理。
        """
        sources = np.asarray(sources, dtype=np.int64)
        out = np.empty((sources.size, self.n_nodes), dtype=float)
        for (a, b), buf in self.iter_dijkstra_many(sources, w, limit, chunk):
            out[a:b] = buf
        return out

    def dijkstra_fast(self, src: int, w: np.ndarray, limit: float = float("inf")) -> np.ndarray:
        """单源最短路；装了 scipy 走 C 实现。"""
        if not HAS_SCIPY:
            return self.dijkstra(src, w, limit)
        g = self.to_csr(w)
        return _scipy_dijkstra(g, directed=True, indices=int(src), limit=limit)

    def dijkstra(self, src: int, w: np.ndarray, limit: float = float("inf")) -> np.ndarray:
        """有界 Dijkstra：超过 limit 的节点不再松弛。"""
        n = self.n_nodes
        dist = np.full(n, np.inf, dtype=float)
        if src < 0 or src >= n:
            return dist
        dist[src] = 0.0
        heap = [(0.0, int(src))]
        indptr = self.indptr
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            if d > limit:
                continue
            for k in range(indptr[u], indptr[u + 1]):
                v = int(self.edge_dst[k])
                nd = d + w[k]
                if nd > limit:
                    continue
                if nd < dist[v] - 1e-12:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        return dist

    def dijkstra_edge_expanded(
        self,
        src: int,
        w: np.ndarray,
        turn_penalty_min: float = 0.0,
        limit: float = float("inf"),
    ) -> np.ndarray:
        """边扩展图上的 Dijkstra，支持转向惩罚与掉头惩罚。

        状态为"有向边"，从边 e (u→v) 转到边 f (v→x) 时按方位角差判定转向：
          直行 0，左/右转 += turn_penalty_min，掉头 += 2 * turn_penalty_min。
        返回按节点聚合的最短时间。
        """
        ne = self.n_edges
        inf = float("inf")
        dist_e = np.full(ne, inf, dtype=float)
        heap = []
        for k in range(self.indptr[src], self.indptr[src + 1]):
            dist_e[k] = w[k]
            heapq.heappush(heap, (w[k], int(k)))

        while heap:
            d, e = heapq.heappop(heap)
            if d > dist_e[e] + 1e-12:
                continue
            if d > limit:
                continue
            v = int(self.edge_dst[e])
            b0 = self.edge_bearing[e]
            for k in range(self.indptr[v], self.indptr[v + 1]):
                # 掉头判定：新边的终点等于当前边的起点
                uturn = self.edge_dst[k] == self.edge_src[e]
                if uturn:
                    extra = 2.0 * turn_penalty_min
                else:
                    db = abs(((self.edge_bearing[k] - b0 + np.pi) % (2 * np.pi)) - np.pi)
                    extra = turn_penalty_min if db > 0.5 else 0.0
                nd = d + w[k] + extra
                if nd > limit:
                    continue
                if nd < dist_e[k] - 1e-12:
                    dist_e[k] = nd
                    heapq.heappush(heap, (nd, k))

        dist_node = np.full(self.n_nodes, inf, dtype=float)
        for e in range(ne):
            if dist_e[e] < dist_node[self.edge_dst[e]]:
                dist_node[self.edge_dst[e]] = dist_e[e]
        dist_node[src] = 0.0
        return dist_node


# --------------------------------------------------------------------------
# 吸附
# --------------------------------------------------------------------------

@dataclass
class SnapResult:
    node: np.ndarray          # 每个点吸附到的节点编号，-1 表示失败
    dist: np.ndarray          # 吸附距离（m）
    ok: np.ndarray            # 是否成功
    failed_share: float
    mean_dist: float


def snap_points(px: np.ndarray, py: np.ndarray, nodes: np.ndarray, max_dist_m: float = 300.0) -> SnapResult:
    """把点吸附到最近路网节点；超限记为失败，不静默取最近节点。

    用均匀网格分桶做空间索引：每个点只比对邻域 9 个桶，邻域内找不到再退回全量比对，
    避免 O(点数 × 节点数) 的平方级开销（10 万单元 × 13 万节点时会从分钟级降到秒级）。
    """
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    n = px.shape[0]
    node = np.full(n, -1, dtype=np.int64)
    best = np.full(n, np.inf, dtype=float)
    if n == 0 or nodes.size == 0:
        return SnapResult(node=node, dist=best, ok=np.zeros(n, dtype=bool),
                          failed_share=1.0, mean_dist=0.0)

    nx, ny = nodes[:, 0], nodes[:, 1]
    # 桶边长取"吸附半径"（上限为研究区的 1/40），保证最近的节点一定落在 3×3 邻域内
    ext = max(float(nx.max() - nx.min()), float(ny.max() - ny.min()), 1.0)
    cell = max(25.0, min(float(max_dist_m), ext / 40.0))

    buckets: Dict[tuple, list] = {}
    bi = np.floor(nx / cell).astype(np.int64)
    bj = np.floor(ny / cell).astype(np.int64)
    for k in range(nodes.shape[0]):
        buckets.setdefault((int(bi[k]), int(bj[k])), []).append(k)

    need_fallback = []
    for i in range(n):
        ci = int(math.floor(px[i] / cell))
        cj = int(math.floor(py[i] / cell))
        cand = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                b = buckets.get((ci + di, cj + dj))
                if b:
                    cand.extend(b)
        if not cand:
            # 桶边长已 ≥ 吸附半径：邻域内没有节点，就说明确实超出半径，直接记失败
            if cell >= max_dist_m - 1e-9:
                best[i] = max_dist_m * 2.0
            else:
                need_fallback.append(i)
            continue
        c = np.asarray(cand, dtype=np.int64)
        d2 = (nx[c] - px[i]) ** 2 + (ny[c] - py[i]) ** 2
        j = int(np.argmin(d2))
        node[i] = c[j]
        best[i] = math.sqrt(float(d2[j]))

    # 邻域为空（孤立点 / 远离路网的目标）才做全量比对
    if need_fallback:
        idx = np.asarray(need_fallback, dtype=np.int64)
        chunk = 256
        for s in range(0, idx.size, chunk):
            e = min(s + chunk, idx.size)
            sel = idx[s:e]
            d2 = (px[sel, None] - nx[None, :]) ** 2 + (py[sel, None] - ny[None, :]) ** 2
            j = np.argmin(d2, axis=1)
            node[sel] = j
            best[sel] = np.sqrt(d2[np.arange(e - s), j])

    ok = best <= max_dist_m
    node = np.where(ok, node, -1)
    return SnapResult(
        node=node,
        dist=best,
        ok=ok,
        failed_share=float((~ok).mean()),
        mean_dist=float(best[ok].mean()) if ok.any() else 0.0,
    )
