# -*- coding: utf-8 -*-
"""数据集序列化：把装配好的 Dataset 存成单文件，供无原始数据的服务器加载。"""
from __future__ import annotations

import os
import pickle
from typing import Optional

__all__ = ["save_bundle", "load_bundle", "BUNDLE_VERSION"]

BUNDLE_VERSION = 1

def save_bundle(ds, path: str, notes=None, extra=None, slim: bool = True) -> str:
    """把 Dataset（含图层、因子、底图）与构建说明打包。

    slim=True 会丢掉网络图层的节点/边数组：服务端重算只用已算好的因子值，
    这些几何只在装配阶段有用，留着会让数据包膨胀十倍以上。
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if slim:
        for lyr in (getattr(ds, "layers", {}) or {}).values():
            if getattr(lyr, "layer_type", "") == "network":
                lyr.nodes = None
                lyr.edges = None
    payload = {
        "version": BUNDLE_VERSION,
        "dataset": ds,
        "notes": list(notes or []),
        "extra": dict(extra or {}),
    }
    with open(path, "wb") as fh:
        pickle.dump(payload, fh, protocol=4)
    return path

def load_bundle(path: str):
    """返回 (Dataset, notes, extra)。"""
    with open(path, "rb") as fh:
        payload = pickle.load(fh)
    if not isinstance(payload, dict) or "dataset" not in payload:
        raise ValueError("不是有效的数据包：%s" % path)
    return payload["dataset"], payload.get("notes", []), payload.get("extra", {})
