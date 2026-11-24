# -*- coding: utf-8 -*-
"""启动 Web 可视化界面。

    python run_web.py                # 默认 http://127.0.0.1:8765/
    python run_web.py --port 8800
    python run_web.py --no-open      # 不自动开浏览器
"""

from __future__ import annotations

import argparse
import sys as _sys

# 版本守卫：放在最前面，避免老 Python 在导入 numpy 时抛出难懂的 SyntaxError
if _sys.version_info < (3, 10):
    _v = '.'.join(str(x) for x in _sys.version_info[:3])
    print('=' * 62)
    print('Python 版本过低：当前 %s，需要 3.10 及以上。' % _v)
    print('')
    print('解决办法（本项目已带好环境，直接运行即可）：')
    print('  Windows:  双击运行  启动.bat')
    print('  或手动:   .venv\\Scripts\\python.exe run_web.py --bundle data/xuhui.bundle')
    print('=' * 62)
    _sys.exit(1)

import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
# 打包成 exe 后，资源被解到 sys._MEIPASS，优先用它
if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
    _BASE = sys._MEIPASS
_VENDOR = os.path.join(_BASE, 'vendor')
if os.path.isdir(_VENDOR):
    sys.path.insert(0, _VENDOR)   # 项目内可选的 scipy/pyogrio；放最前保证 numpy 版本配套
sys.path.insert(0, _BASE)

from seba.webapp import serve  # noqa: E402

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="空间显式批量评估工作台系统 * Web 可视化版")
    ap.add_argument("--config", default=os.path.join("config", "factors.yaml"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", default="out_web", help="导出产物目录")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--bundle", default=None, metavar="文件",
                    help="直接加载预打包的数据集（无需原始地理数据）")
    ap.add_argument("--export-bundle", default=None, metavar="文件",
                    help="把当前真实数据装配结果打包保存，供服务器使用")
    ap.add_argument("--districts", default=None, metavar="目录",
                    help="内置多区数据目录：启动后先让用户选区")
    ap.add_argument("--real", default=None, metavar="区县",
                    help="使用真实数据（上海村界+真实路网），如：徐汇区")
    args = ap.parse_args(argv)
    # 云端平台会用环境变量注入端口与监听地址
    if os.environ.get("PORT"):
        args.port = int(os.environ["PORT"])
    if os.environ.get("HOST"):
        args.host = os.environ["HOST"]

    base = _BASE
    cfg = args.config if os.path.isabs(args.config) else os.path.join(base, args.config)
    out = args.out if os.path.isabs(args.out) else os.path.join(base, args.out)
    if not os.path.exists(cfg):
        print("找不到配置文件：%s" % cfg, file=sys.stderr)
        return 2

    if args.export_bundle:
        from seba.realdata import build_district_dataset
        from seba.bundle import save_bundle

        district = None if args.real in ("全市", "all") else (args.real or "徐汇区")
        print("[1/2] 装配真实数据并打包：%s" % (district or "全市"))
        ds, rep = build_district_dataset(district)
        # 必须先把因子算进 ds.attrs，否则包里没有结果、服务器还得重算
        from seba.config import ProjectConfig
        from seba.engine import FactorEngine

        with open(os.path.join(base, "config", "factors_real.yaml"), "r", encoding="utf-8") as fh:
            cfgx = ProjectConfig.from_yaml(fh.read())
        FactorEngine(cfgx, ds).run()
        print("      因子已计算：%d 个" % len(ds.attrs))
        save_bundle(ds, args.export_bundle, rep.notes, {"district": district or "全市"})
        print("      已保存 %s（%.1f MB，%d 单元）"
              % (args.export_bundle, os.path.getsize(args.export_bundle) / 1048576, ds.n_units))
        return 0

    if args.districts:
        from seba.webapp.server import make_server

        ddir = args.districts if os.path.isabs(args.districts) else os.path.join(base, args.districts)
        cfg = os.path.join(base, "config", "factors_real.yaml")
        names = [f[:-7] for f in os.listdir(ddir) if f.endswith(".bundle")] if os.path.isdir(ddir) else []
        print("[1/2] 内置 %d 个区，启动后由用户选择" % len(names))
        h, state = make_server(cfg, args.host, args.port, out, dataset=None,
                               notes=None, source="multi", prebuilt=True, districts_dir=ddir)
        import webbrowser

        url = "http://%s:%d/" % (args.host, args.port)
        print("[2/2] 服务已启动：%s" % url)
        if not args.no_open:
            webbrowser.open(url)
        try:
            h.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
        finally:
            h.server_close()
        return 0

    if args.bundle:
        from seba.bundle import load_bundle
        from seba.webapp.server import make_server

        print("[1/2] 加载数据包：%s" % args.bundle)
        ds, notes, extra = load_bundle(args.bundle)
        cfg = os.path.join(base, "config", "factors_real.yaml")
        print("      %d 单元 / %d 成交" % (ds.n_units, ds.n_obs()))
        h, state = make_server(cfg, args.host, args.port, out, dataset=ds,
                               notes=notes, source="bundle", prebuilt=True)
        import webbrowser

        url = "http://%s:%d/" % (args.host, args.port)
        print("[2/2] 服务已启动：%s" % url)
        if not args.no_open:
            webbrowser.open(url)
        try:
            h.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
        finally:
            h.server_close()
        return 0

    if args.real:
        from seba.realdata import build_district_dataset

        district = None if args.real in ("全市", "all") else args.real
        print("[0/2] 装配真实地理数据（%s），约需 10-60 秒 ..." % (args.real,))
        ds, rep = build_district_dataset(district)
        cfg = os.path.join(base, "config", "factors_real.yaml")
        print("      完成：%d 单元 / %d 成交" % (ds.n_units, ds.n_obs()))
        from seba.webapp.server import make_server

        h, state = make_server(cfg, args.host, args.port, out, dataset=ds,
                               notes=rep.notes, source="real")
        import webbrowser

        url = "http://%s:%d/" % (args.host, args.port)
        print("[2/2] 服务已启动：%s" % url)
        if not args.no_open:
            webbrowser.open(url)
        try:
            h.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")
        finally:
            h.server_close()
        return 0

    serve(cfg, host=args.host, port=args.port, out_dir=out, open_browser=not args.no_open)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
