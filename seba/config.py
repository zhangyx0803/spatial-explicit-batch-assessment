# -*- coding: utf-8 -*-
"""声明式因子配置：YAML 子集解析、结构校验与哈希。

只依赖标准库。支持本工程用到的 YAML 子集：
  - 注释（# 起，引号内不算）
  - 映射 key: value
  - 序列 - item
  - 行内列表 [a, b, c] 与行内映射 {k: v, k2: v2}
  - 标量：int / float / bool / null / 引号串 / 普通串

设计意图：因子由配置声明而不是硬编码。新增一个因子只改配置文件，
引擎负责解析、拓扑排序、执行与缓存。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "ConfigError",
    "load_yaml",
    "FactorSpec",
    "ProjectConfig",
    "OPS",
]

class ConfigError(ValueError):
    """配置结构或参数非法。"""

# 1. YAML 子集解析

def _strip_comment(line: str) -> str:
    """去掉行尾注释，引号内的 # 不算注释。"""
    out: List[str] = []
    quote: Optional[str] = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()

def _cast(tok: str) -> Any:
    t = tok.strip()
    if not t:
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    low = t.lower()
    if low in ("null", "~", "none"):
        return None
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?", t) and any(c in t for c in ".eE"):
        return float(t)
    return t

def _split_top(s: str, sep: str = ",") -> List[str]:
    """按顶层分隔符切分，忽略括号与引号内部的逗号。"""
    parts: List[str] = []
    depth = 0
    quote: Optional[str] = None
    cur: List[str] = []
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
            continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts

def _scalar(s: str) -> Any:
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [] if not inner else [_scalar(p) for p in _split_top(inner)]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        d: Dict[str, Any] = {}
        if not inner:
            return d
        for p in _split_top(inner):
            k, sep, v = p.partition(":")
            if not sep:
                raise ConfigError("行内映射缺少冒号：%r" % p)
            d[k.strip().strip("\"'")] = _scalar(v)
        return d
    return _cast(s)

def _prepare(text: str) -> List[tuple]:
    rows: List[tuple] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[:indent]:
            raise ConfigError("缩进不能使用 Tab 字符")
        rows.append((indent, line.strip()))
    return rows

_KEY_RE = re.compile(r"^[A-Za-z_\u4e00-\u9fff][\w\-. ]*:(\s|$)")

def _parse_node(rows: List[tuple], i: int, indent: int) -> tuple:
    ind, txt = rows[i]
    # 序列
    if txt.startswith("- "):
        seq: List[Any] = []
        while i < len(rows):
            ind2, txt2 = rows[i]
            if ind2 != indent or not txt2.startswith("- "):
                break
            body = txt2[2:].strip()
            j = i + 1
            block: List[tuple] = []
            while j < len(rows) and rows[j][0] > indent:
                block.append(rows[j])
                j += 1
            if not block and not _KEY_RE.match(body):
                # 纯标量序列项
                seq.append(_scalar(body))
                i = j
                continue
            if body:
                block.insert(0, (indent + 2, body))
            if block:
                val, _ = _parse_node(block, 0, indent + 2)
                seq.append(val)
            else:
                seq.append(None)
            i = j
        return seq, i

    # 映射
    mp: Dict[str, Any] = {}
    while i < len(rows):
        ind2, txt2 = rows[i]
        if ind2 != indent:
            break
        if txt2.startswith("- "):
            break
        if ":" not in txt2:
            raise ConfigError("此处应为 key: value，实际是 %r" % txt2)
        k, _, v = txt2.partition(":")
        key = k.strip().strip("\"'")
        val_txt = v.strip()
        i += 1
        if val_txt:
            mp[key] = _scalar(val_txt)
        elif i < len(rows) and rows[i][0] > indent:
            mp[key], i = _parse_node(rows, i, rows[i][0])
        else:
            mp[key] = None
    return mp, i

def load_yaml(text: str) -> Any:
    """解析 YAML 子集文本，返回 dict / list。"""
    rows = _prepare(text)
    if not rows:
        return {}
    val, i = _parse_node(rows, 0, rows[0][0])
    if i != len(rows):
        raise ConfigError("第 %d 行附近缩进不一致" % (i + 1))
    return val

# 2. 算子注册表：每个算子的必填输入、参数与单位要求

@dataclass(frozen=True)
class OpSpec:
    name: str
    required_inputs: tuple
    optional_inputs: tuple = ()
    required_params: tuple = ()
    optional_params: tuple = ()
    outputs: tuple = ()
    note: str = ""

OPS: Dict[str, OpSpec] = {
    "network_shortest_path": OpSpec(
        "network_shortest_path",
        required_inputs=("network", "destinations"),
        optional_inputs=("origins",),
        required_params=("mode",),
        optional_params=("snap", "turn_penalty_min"),
        outputs=("dist_m", "t_min"),
        note="阻抗加权 Dijkstra，返回网络距离与行程时间",
    ),
    "network_isochrone": OpSpec(
        "network_isochrone",
        required_inputs=("network", "destinations"),
        optional_inputs=("origins",),
        required_params=("mode", "thresholds_min"),
        optional_params=("snap", "impedance"),
        outputs=("t_min", "n_reached"),
        note="有界 Dijkstra 切出可达集合后计数",
    ),
    "gravity_access": OpSpec(
        "gravity_access",
        required_inputs=("opportunity", "dist"),
        required_params=("impedance",),
        optional_params=("mass",),
        outputs=("index",),
        note="A_i = Σ_j O_j * f(d_ij)",
    ),
    "two_step_floating_catchment": OpSpec(
        "two_step_floating_catchment",
        required_inputs=("supply", "demand", "network"),
        required_params=("threshold_min", "decay"),
        optional_params=("snap", "mode"),
        outputs=("sfca_index",),
        note="2SFCA：先算供需比再按需求点聚合",
    ),
    "distance_decay": OpSpec(
        "distance_decay",
        required_inputs=("dist",),
        required_params=("impedance",),
        outputs=("value",),
        note="对距离施加衰减函数",
    ),
    "buffer_overlay": OpSpec(
        "buffer_overlay",
        required_inputs=("layer",),
        required_params=("radius_m", "stat"),
        outputs=("value",),
        note="缓冲区内计数 / 面积占比 / 加权密度",
    ),
    "spatial_join_agg": OpSpec(
        "spatial_join_agg",
        required_inputs=("layer",),
        required_params=("stat",),
        optional_params=("k", "radius_m"),
        outputs=("value",),
        note="最近邻取值、k 近邻均值、半径内统计",
    ),
    "kernel_density": OpSpec(
        "kernel_density",
        required_inputs=("layer",),
        required_params=("bandwidth_m",),
        outputs=("value",),
        note="核密度估计",
    ),
    "network_topology": OpSpec(
        "network_topology",
        required_inputs=("network",),
        required_params=("radius_m", "stat"),
        outputs=("intersection_density", "deadend_ratio"),
        note="交叉口密度、尽端路比例等路网拓扑指标",
    ),
    "attribute": OpSpec(
        "attribute",
        required_inputs=("field",),
        outputs=("value",),
        note="直接读取属性字段（规划、建筑类因子）",
    ),
    "raster_extract": OpSpec(
        "raster_extract",
        required_inputs=("raster",),
        required_params=("stat",),
        outputs=("value",),
        note="栅格取值 / 面内统计，处理 NoData",
    ),
}

VALID_MODES = ("drive", "walk", "bike")
IMPERANCE_TYPES = ("exponential", "power", "gaussian")

# 3. 配置对象

@dataclass
class FactorSpec:
    code: str
    op: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)
    enabled: bool = True
    note: str = ""

    def signature(self) -> str:
        """参数指纹：参与缓存键。"""
        blob = json.dumps(
            {"op": self.op, "inputs": self.inputs, "params": self.params},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)

def _check_snap(params: Dict[str, Any], where: str) -> None:
    snap = params.get("snap")
    if snap is None:
        return
    _require(isinstance(snap, dict), "%s: snap 必须是映射" % where)
    _require(
        snap.get("method", "nearest_node") in ("nearest_node", "centroid_then_node"),
        "%s: snap.method 取值非法" % where,
    )
    md = snap.get("max_dist_m", 300)
    _require(isinstance(md, (int, float)) and md > 0, "%s: snap.max_dist_m 必须为正数" % where)

def _validate_factor(f: FactorSpec) -> None:
    where = "因子 %s" % f.code
    _require(f.op in OPS, "%s: 未知算子 %r（可选：%s）" % (where, f.op, ", ".join(sorted(OPS))))
    spec = OPS[f.op]

    for key in spec.required_inputs:
        _require(key in f.inputs and f.inputs[key] not in (None, ""), "%s: 缺少输入 %s" % (where, key))
    for key in spec.required_params:
        _require(key in f.params and f.params[key] is not None, "%s: 缺少参数 %s" % (where, key))

    known = set(spec.required_inputs) | set(spec.optional_inputs)
    for key in f.inputs:
        _require(key in known, "%s: 算子 %s 不接受输入 %r" % (where, f.op, key))
    knownp = set(spec.required_params) | set(spec.optional_params)
    for key in f.params:
        _require(key in knownp, "%s: 算子 %s 不接受参数 %r" % (where, f.op, key))

    # 单位后缀：凡时间类参数必须显式带 _min，防止单位混用
    for key in f.params:
        if "penalty" in key or "time" in key:
            _require(key.endswith(("_min", "_s")), "%s: 时间参数 %r 必须以 _min 或 _s 结尾" % (where, key))

    if f.op in ("network_shortest_path", "network_isochrone", "two_step_floating_catchment"):
        mode = f.params.get("mode", "walk")
        _require(mode in VALID_MODES, "%s: mode 取值非法" % where)
        _check_snap(f.params, where)

    if "impedance" in f.params:
        imp = f.params["impedance"]
        _require(isinstance(imp, dict), "%s: impedance 必须是映射" % where)
        _require(imp.get("type") in IMPERANCE_TYPES, "%s: impedance.type 取值非法" % where)
        if imp.get("type") == "gaussian":
            _require("sigma" in imp or "sigma_min" in imp, "%s: 高斯衰减必须给 sigma" % where)

    if f.op == "two_step_floating_catchment":
        dec = f.params.get("decay")
        _require(isinstance(dec, dict), "%s: decay 必须是映射" % where)
        if dec.get("type") == "gaussian":
            _require("sigma" in dec or "sigma_min" in dec, "%s: 2SFCA 高斯衰减必须给 sigma" % where)

    if not f.outputs:
        f.outputs = list(spec.outputs) or ["value"]

@dataclass
class ProjectConfig:
    name: str
    crs: str
    layers: Dict[str, Dict[str, Any]]
    factors: List[FactorSpec]
    model: Dict[str, Any]
    valuation: Dict[str, Any]
    diagnosis: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)

    # 构造与校验
    @classmethod
    def from_yaml(cls, text: str) -> "ProjectConfig":
        doc = load_yaml(text)
        _require(isinstance(doc, dict), "配置根节点必须是映射")
        for key in ("project", "layers", "factors"):
            _require(key in doc, "缺少顶层节点 %r" % key)

        proj = doc["project"] or {}
        name = proj.get("name") or "未命名工程"
        crs = proj.get("crs") or "CGCS2000_3_degree_zone"
        _require("area_of_interest" in proj, "project 缺少 area_of_interest")

        layers = doc["layers"] or {}
        _require(isinstance(layers, dict) and layers, "layers 必须是非空映射")
        for lid, spec in layers.items():
            _require(isinstance(spec, dict), "图层 %s 定义必须是映射" % lid)
            _require("type" in spec, "图层 %s 缺少 type" % lid)
            _require(
                spec["type"] in ("network", "point", "polygon", "raster"),
                "图层 %s: type 必须是 network/point/polygon/raster" % lid,
            )
            _require("version" in spec, "图层 %s 缺少 version（缓存键需要）" % lid)

        flist = doc["factors"] or []
        _require(isinstance(flist, list) and flist, "factors 必须是非空序列")
        factors: List[FactorSpec] = []
        seen = set()
        for item in flist:
            _require(isinstance(item, dict), "factors 的每一项必须是映射")
            code = item.get("code")
            _require(bool(code), "因子缺少 code")
            _require(code not in seen, "因子编码重复：%s" % code)
            seen.add(code)
            f = FactorSpec(
                code=code,
                op=item.get("op", ""),
                inputs=item.get("inputs") or {},
                params=item.get("params") or {},
                outputs=list(item.get("outputs") or []),
                enabled=bool(item.get("enabled", True)),
                note=item.get("note", ""),
            )
            if f.enabled:
                _validate_factor(f)
                factors.append(f)

        _require(factors, "没有启用的因子")

        cfg = cls(
            name=name,
            crs=crs,
            layers=layers,
            factors=factors,
            model=doc.get("model") or {},
            valuation=doc.get("valuation") or {},
            diagnosis=doc.get("diagnosis") or {},
            raw=doc,
        )
        cfg._validate_refs()
        return cfg

    def _validate_refs(self) -> None:
        """校验 inputs 里引用的图层与因子是否真实存在。"""
        codes = {f.code for f in self.factors}
        for f in self.factors:
            for key, val in f.inputs.items():
                if isinstance(val, str):
                    if val.startswith("factor:"):
                        ref = val.split(":", 1)[1]
                        _require(ref in codes, "%s: 引用了不存在的因子 %r" % (f.code, ref))
                    elif val.startswith("field:"):
                        continue
                    else:
                        _require(val in self.layers, "%s: 引用了未注册的图层 %r" % (f.code, val))

    # DAG
    def dependencies(self) -> Dict[str, List[str]]:
        deps: Dict[str, List[str]] = {}
        for f in self.factors:
            d = []
            for val in f.inputs.values():
                if isinstance(val, str) and val.startswith("factor:"):
                    d.append(val.split(":", 1)[1])
            deps[f.code] = d
        return deps

    def topological_order(self) -> List[str]:
        deps = self.dependencies()
        order: List[str] = []
        state: Dict[str, int] = {}

        def visit(node: str, stack: List[str]) -> None:
            st = state.get(node, 0)
            if st == 1:
                cyc = " -> ".join(stack[stack.index(node):] + [node])
                raise ConfigError("因子依赖存在环：%s" % cyc)
            if st == 2:
                return
            state[node] = 1
            stack.append(node)
            for d in deps.get(node, []):
                visit(d, stack)
            stack.pop()
            state[node] = 2
            order.append(node)

        for f in self.factors:
            visit(f.code, [])
        return order

    def factor(self, code: str) -> FactorSpec:
        for f in self.factors:
            if f.code == code:
                return f
        raise KeyError(code)

    def snapshot(self) -> str:
        """配置快照：写进运行日志与报告页脚，保证可复现。"""
        return json.dumps(self.raw, ensure_ascii=False, sort_keys=True, indent=2)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.snapshot().encode("utf-8")).hexdigest()[:12]
