# -*- coding: utf-8 -*-
"""本地 Web 可视化界面（标准库 HTTP 服务 + 原生前端）。"""

from .server import make_server, serve

__all__ = ["serve", "make_server"]
