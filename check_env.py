# -*- coding: utf-8 -*-
"""部署前环境自检：确认依赖齐全、模块可导入、数据包可加载。

用法：python check_env.py [数据包路径]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_v):
    sys.path.insert(0, _v)

FAIL = 0

def step(name, fn):
    global FAIL
    try:
        msg = fn()
        print("  [OK]   %-22s %s" % (name, msg or ""))
    except Exception as exc:
        FAIL += 1
        print("  [FAIL] %-22s %s: %s" % (name, type(exc).__name__, exc))

print("=" * 62)
print("空间显式批量评估工作台 - 环境自检")
print("=" * 62)
print("Python %s" % sys.version.split()[0])

print("\n[1] 必需依赖")

def _dep():
    import docx, numpy, openpyxl, pandas, PIL  # noqa: F401
    return "numpy %s / pandas %s" % (numpy.__version__, pandas.__version__)

step("numpy pandas 等", _dep)

print("\n[2] 可选依赖（缺了也能跑，只是慢一些）")
for name in ("scipy", "pyogrio", "shapely"):
    try:
        m = __import__(name)
        print("  [有]   %-22s %s" % (name, getattr(m, "__version__", "")))
    except Exception:
        print("  [无]   %-22s 将走纯 Python 实现" % name)

print("\n[3] 核心模块")

def _mods():
    import seba.bundle, seba.centralplace, seba.intake, seba.vec  # noqa: F401
    return "vec / intake / centralplace / bundle"

step("模块导入", _mods)

print("\n[4] 数据包")
p = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "districts/徐汇区.bundle")
if not os.path.exists(p):
    print("  [FAIL] 数据包不存在：%s" % p)
    FAIL += 1
else:

    def _bundle():
        from seba.bundle import load_bundle

        ds, notes, extra = load_bundle(p)
        assert ds.n_units > 0, "数据包为空"
        assert ds.attrs, "数据包里没有因子结果"
        return "%d 单元 / %d 成交 / %d 因子" % (ds.n_units, ds.n_obs(), len(ds.attrs))

    step("加载 %s" % os.path.basename(p), _bundle)

print("\n" + "=" * 62)
print("通过" if FAIL == 0 else "有 %d 项失败" % FAIL)
print("=" * 62)
sys.exit(1 if FAIL else 0)
