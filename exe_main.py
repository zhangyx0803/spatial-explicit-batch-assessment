# -*- coding: utf-8 -*-
"""双击 exe 的入口：自动找空闲端口、加载内置数据包、打开浏览器。

打包命令见 build_exe.py / build_exe.ps1。
"""
from __future__ import annotations

import os
import socket
import sys
import time
import webbrowser


def _base() -> str:
    """打包后资源在 sys._MEIPASS，开发时在脚本目录。"""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _free_port(start: int = 8765, tries: int = 30) -> int:
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def main() -> int:
    base = _base()
    bundle = os.path.join(base, "data", "demo_xuhui.bundle")

    banner = r"""
  ____  _____ ____    _
 / ___|| ____| __ )  / \      Space-Explicit Batch Assessment
 \___ \|  _| |  _ \ / _ \     空间显式批量评估工作台 V1.0
  ___) | |___| |_) / ___ \    http://127.0.0.1:{port}
 |____/|_____|____/_/   \_\
"""
    if not os.path.exists(bundle):
        print("[错误] 找不到数据包：%s" % bundle)
        print("       请确认 exe 与 data 文件夹在同一个目录下。")
        input("按回车退出…")
        return 2

    port = _free_port()
    print(banner.format(port=port))
    print("  正在启动，稍后会自动打开浏览器……")
    print("  关闭这个黑窗口即停止服务。")
    print("=" * 68)

    # 延迟开浏览器：等服务真正起来
    def _open_later():
        for _ in range(60):
            time.sleep(0.5)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    webbrowser.open("http://127.0.0.1:%d/" % port)
                    return
            except OSError:
                continue

    import threading

    threading.Thread(target=_open_later, daemon=True).start()

    sys.argv = [sys.argv[0], "--bundle", bundle, "--port", str(port)]
    from run_web import main as web_main

    try:
        return web_main()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # 打包后没有控制台回溯时也能看到原因
        print("\n[启动失败] %s: %s" % (type(exc).__name__, exc))
        import traceback

        traceback.print_exc()
        input("\n按回车退出…")
        return 1


if __name__ == "__main__":
    sys.exit(main())
