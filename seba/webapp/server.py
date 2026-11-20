# -*- coding: utf-8 -*-
"""Web 版后端：标准库 http.server，不引入 Flask / FastAPI。

路由：
    GET  /                 单页应用
    GET  /static/...       静态资源
    GET  /api/bootstrap    工程概况 + 单元索引 + 默认运行结果
    POST /api/run          按选中的特征重训，返回指标与图层数组
    GET  /api/field?code=  取某个因子的逐单元取值（地图按因子查看）
    GET  /api/unit?i=      单元详情
    POST /api/export       生成 xlsx / docx / png
    GET  /files/<name>     下载导出产物
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .state import AppState

__all__ = ["serve", "make_server"]

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class Handler(BaseHTTPRequestHandler):
    server_version = "SEBA/1.0"
    state: AppState = None          # 由 make_server 注入
    out_dir: str = None
    lock = threading.Lock()

    # ---------------- 基础工具 ----------------
    def log_message(self, fmt, *args):   # 静音访问日志，只留错误
        return

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def _error(self, code: int, msg: str):
        self._json({"ok": False, "error": msg}, code)

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _file(self, rel: str):
        safe = posixpath.normpath("/" + rel).lstrip("/")
        path = os.path.join(STATIC_DIR, safe)
        if not os.path.abspath(path).startswith(os.path.abspath(STATIC_DIR)):
            return self._error(403, "forbidden")
        if not os.path.exists(path):
            return self._error(404, "not found: %s" % safe)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # ---------------- 路由 ----------------
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self._file("index.html")
            if p.startswith("/static/"):
                return self._file(p[len("/static/"):])
            if p == "/api/bootstrap":
                return self._json({"ok": True, **self.state.bootstrap()})
            if p == "/api/field":
                code = (q.get("code") or [""])[0]
                return self._json({"ok": True, **self.state.field(code)})
            if p == "/api/unit":
                i = int((q.get("i") or ["0"])[0])
                return self._json({"ok": True, **self.state.unit_detail(i)})
            if p == "/api/districts":
                st = self.state
                return self._json({"ok": True, "current": getattr(st, "current", None),
                                   "districts": getattr(st, "districts", [])})
            if p.startswith("/files/"):
                name = os.path.basename(p[len("/files/"):])
                path = os.path.join(self.out_dir, name)
                if not os.path.exists(path):
                    return self._error(404, "文件不存在，请先导出")
                ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
                with open(path, "rb") as fh:
                    return self._send(200, fh.read(), ctype)
            return self._error(404, "no route: %s" % p)
        except Exception as exc:          # 不让异常打断服务
            traceback.print_exc()
            return self._error(500, "%s: %s" % (type(exc).__name__, exc))

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        try:
            if p == "/api/run":
                body = self._read_json()
                feats = body.get("features") or []
                with self.lock:
                    res = self.state.fit(feats)
                    self.state.features = res["features"]
                    self.state.result = res
                return self._json({"ok": True, **res})

            if p == "/api/preview":
                body = self._read_json()
                with self.lock:
                    info = self.state.preview(body.get("b64") or "", body.get("kind") or "units")
                return self._json({"ok": True, **info})

            if p == "/api/districts":
                st = self.state
                return self._json({"ok": True, "current": getattr(st, "current", None),
                                   "districts": getattr(st, "districts", [])})

            if p == "/api/district":
                body = self._read_json()
                name = (body.get("name") or "").strip()
                if not name:
                    raise ValueError("缺少区名")
                with self.lock:
                    info = self.state.switch_district(name)
                return self._json({"ok": True, **info})

            if p == "/api/decompose":
                body = self._read_json()
                with self.lock:
                    info = self.state.decompose_unit(
                        int(body.get("i") or 0),
                        price=body.get("price") or None,
                        radius=float(body.get("radius") or 1500.0),
                        min_n=int(body.get("min_n") or 60),
                    )
                return self._json({"ok": True, **info})

            if p == "/api/intake/upload":
                body = self._read_json()
                with self.lock:
                    info = self.state.intake_upload(body.get("files") or [])
                return self._json(info)

            if p == "/api/intake/sample":
                with self.lock:
                    info = self.state.intake_sample()
                return self._json(info)

            if p == "/api/intake/analyze":
                body = self._read_json()
                with self.lock:
                    info = self.state.intake_analyze(body.get("paths") or [])
                return self._json(info)

            if p == "/api/intake/apply":
                body = self._read_json()
                with self.lock:
                    info = self.state.intake_apply(body)
                return self._json(info)

            if p == "/api/import":
                body = self._read_json()
                with self.lock:
                    info = self.state.import_data(body.get("spec") or {})
                return self._json({"ok": True, **info, **self.state.bootstrap()})

            if p == "/api/reset":
                with self.lock:
                    self.state.reset_demo()
                return self._json({"ok": True, **self.state.bootstrap()})

            if p == "/api/factors/update":
                body = self._read_json()
                with self.lock:
                    self.state.update_factors(body.get("changes") or {})
                return self._json({"ok": True, **self.state.bootstrap()})

            if p == "/api/factors/add":
                body = self._read_json()
                with self.lock:
                    info = self.state.add_factor(
                        body.get("template") or "",
                        body.get("name") or "",
                        body.get("mapping") or {},
                        body.get("params") or {},
                    )
                return self._json({"ok": True, **info, **self.state.bootstrap()})

            if p == "/api/export":
                with self.lock:
                    files = self.state.export(self.out_dir)
                names = [os.path.basename(f) for f in files]
                return self._json({"ok": True, "files": names, "dir": self.out_dir})

            return self._error(404, "no route: %s" % p)
        except Exception as exc:
            traceback.print_exc()
            return self._error(500, "%s: %s" % (type(exc).__name__, exc))


def make_server(cfg_path: str, host: str = "127.0.0.1", port: int = 8765,
                out_dir: str = "out_web", verbose: bool = True,
                dataset=None, notes=None, source: str = "demo", prebuilt: bool = False,
   districts_dir: str = None):
    if verbose:
        print("[1/2] 加载工程、执行因子 DAG …")
    state = AppState(cfg_path, dataset=dataset, notes=notes, source=source,
                     prebuilt=prebuilt, districts_dir=districts_dir)
    if verbose and getattr(state, "ds", None) is None:
        print("      未加载数据：等待用户选择行政区（内置 %d 个）"
              % len(getattr(state, "districts", [])))
    elif verbose:
        print("      完成：%d 单元 / %d 成交 / %d 因子，用时 %.1fs"
              % (state.ds.n_units, state.ds.n_obs(),
               len(state.rep.runs) if state.rep is not None else 0, state.load_seconds))

    Handler.state = state
    Handler.out_dir = os.path.abspath(out_dir)

    class _S(ThreadingHTTPServer):
        daemon_threads = True

    return _S((host, port), Handler), state


def serve(cfg_path: str, host: str = "127.0.0.1", port: int = 8765,
          out_dir: str = "out_web", open_browser: bool = True) -> None:
    httpd, state = make_server(cfg_path, host, port, out_dir)
    url = "http://%s:%d/" % (host, port)
    print("[2/2] 服务已启动：%s" % url)
    print("      按 Ctrl+C 停止。产物导出到：%s" % os.path.abspath(out_dir))
    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
