# -*- coding: utf-8 -*-
"""双击 exe 的入口。

设计原则：双击之后不管成功还是失败，用户都必须能看到「发生了什么」——
失败时窗口不能一闪而过，成功时要明确告诉地址。
所有输出同时写入日志文件，方便远程排查。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser

APP = "空间显式批量评估工作台系统 V1.0"


def _fix_console() -> None:
    """Windows 控制台默认 GBK，中文会显示成乱码，这里强制切到 UTF-8。"""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

_T0 = time.time()


def _base() -> str:
    """打包后资源在 sys._MEIPASS，开发时在脚本目录。"""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _exe_dir() -> str:
    """exe 所在目录（日志写这里，方便用户直接找到发给我）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_LOG_PATH = ""


def _init_log() -> None:
    _fix_console()
    global _LOG_PATH
    for d in (_exe_dir(), os.environ.get("TEMP", "")):
        if not d:
            continue
        p = os.path.join(d, "启动日志.txt")
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("%s 启动于 %s\nPython %s\n" % (
                    APP, time.strftime("%Y-%m-%d %H:%M:%S"), sys.version.split()[0]))
            _LOG_PATH = p
            return
        except Exception:
            continue


def log(msg: str) -> None:
    print(msg, flush=True)
    if _LOG_PATH:
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except Exception:
            pass


def _free_port(start: int = 8765, tries: int = 40) -> int:
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 0


def _holding(port: int) -> int:
    """如果端口已被占用，判断是不是本程序已经在跑（是则直接开浏览器）。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        return 0
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:%d/api/bootstrap" % port, timeout=3) as r:
            body = r.read(400)
        return 1 if (b"project" in body or b"n_units" in body) else 2
    except Exception:
        return 2


def selftest() -> int:
    """诊断模式：把环境信息打出来，用户截图发回来即可定位问题。"""
    log("=" * 60)
    log(" 诊断模式")
    log("=" * 60)
    log("程序目录   : %s" % _exe_dir())
    log("资源目录   : %s" % _base())
    log("日志文件   : %s" % (_LOG_PATH or "（无法写入）"))
    log("Python     : %s" % sys.version.replace("\n", " "))
    log("临时目录   : %s" % os.environ.get("TEMP", "?"))
    bundle = os.path.join(_base(), "data", "demo_xuhui.bundle")
    log("数据包     : %s  %s" % (bundle, "存在" if os.path.exists(bundle) else "缺失！"))
    if os.path.exists(bundle):
        log("            %.1f MB" % (os.path.getsize(bundle) / 1048576))
    static = os.path.join(_base(), "seba", "webapp", "static", "index.html")
    log("前端页面   : %s  %s" % (static, "存在" if os.path.exists(static) else "缺失！"))
    p = _free_port()
    log("可用端口   : %s" % (p or "8765-8804 全部被占用"))
    for port in (8765, 8766, 8767):
        h = _holding(port)
        if h == 1:
            log("端口 %d   : 已有本程序的实例在运行 → http://127.0.0.1:%d/" % (port, port))
            break
        if h == 2:
            log("端口 %d   : 被其他程序占用" % port)
    try:
        import numpy

        log("numpy      : %s" % numpy.__version__)
    except Exception as exc:
        log("numpy      : 导入失败 %s" % exc)
    log("=" * 60)
    log("以上信息截图发回即可。")
    return 0


def main() -> int:
    _init_log()

    if "--selftest" in sys.argv or "-t" in sys.argv:
        try:
            return selftest()
        finally:
            _pause()

    base = _base()
    bundle = os.path.join(base, "data", "demo_xuhui.bundle")

    log("")
    log("  " + "=" * 56)
    log("   " + APP)
    log("   Space-Explicit Batch Assessment｜空间显式批量评估")
    log("  " + "=" * 56)
    log("")

    # 已经有一个实例在跑：直接开浏览器，不重复启动
    for port in (8765, 8766, 8767):
        if _holding(port) == 1:
            log("  程序已经启动过了，直接打开页面：http://127.0.0.1:%d/" % port)
            webbrowser.open("http://127.0.0.1:%d/" % port)
            log("")
            log("  如果浏览器没反应，手动复制上面的地址到浏览器打开。")
            log("  关闭本窗口不会影响已经在运行的那一个。")
            _pause()
            return 0

    if not os.path.exists(bundle) and not os.path.isdir(os.path.join(base, "data", "districts")):
        log("  [错误] 找不到数据包：")
        log("         %s" % bundle)
        log("")
        log("  可能原因：exe 被单独拷出来了，没有和 data 目录在一起。")
        log("  正确用法：解压整个压缩包，双击里面的 exe。")
        _pause()
        return 2

    port = _free_port()
    if not port:
        log("  [错误] 8765-8804 端口全部被占用，请关闭其他程序后重试。")
        _pause()
        return 3

    url = "http://127.0.0.1:%d/" % port
    log("  正在启动服务（首次约 5-10 秒）……")
    log("")
    log("  ★ 访问地址： %s" % url)
    log("  ★ 浏览器会自动打开；若没打开，手动复制上面地址")
    log("  ★ 关闭这个黑窗口就停止服务")
    log("  " + "-" * 56)
    log("")

    def _open_later():
        for _ in range(80):
            time.sleep(0.4)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    time.sleep(0.6)
                    webbrowser.open(url)
                    log("  [浏览器已唤起] %s" % url)
                    return
            except OSError:
                continue
        log("  [提示] 浏览器未能自动打开，请手动访问 %s" % url)

    threading.Thread(target=_open_later, daemon=True).start()

    ddir = os.path.join(base, "data", "districts")
    if os.path.isdir(ddir) and any(f.endswith(".bundle") for f in os.listdir(ddir)):
        log("           内置多区模式：%d 个区" % len([f for f in os.listdir(ddir) if f.endswith(".bundle")]))
        # exe_main 已经负责唤起浏览器；给 run_web 传 --no-open，避免开两个标签页。
        sys.argv = [sys.argv[0], "--districts", ddir, "--port", str(port), "--no-open"]
    else:
        sys.argv = [sys.argv[0], "--bundle", bundle, "--port", str(port), "--no-open"]
    from run_web import main as web_main

    try:
        return web_main()
    except KeyboardInterrupt:
        log("\n  已停止。")
        return 0
    except Exception:
        log("\n  [启动失败] 错误详情：")
        log(traceback.format_exc())
        log("  日志已保存到：%s" % _LOG_PATH)
        log("  把这个窗口截图发回即可定位问题。")
        _pause()
        return 1


def _pause() -> None:
    try:
        input("\n按回车键退出…")
    except Exception:
        time.sleep(30)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        try:
            log(traceback.format_exc())
        except Exception:
            pass
        _pause()
        sys.exit(1)
