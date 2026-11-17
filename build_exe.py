# -*- coding: utf-8 -*-
"""把工作台打包成 Windows 单文件 exe。

用法：
    .venv\\Scripts\\python.exe -m pip install pyinstaller
    .venv\\Scripts\\python.exe build_exe.py

产物：dist/空间显式批量评估工作台.exe（约 60–90 MB，双击即用）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "空间显式批量评估工作台"

# 需要一并打包进 exe 的目录（相对项目根）
ADD_DIRS = [
    ("config", "config"),
    ("data", "data"),
    ("seba/webapp/static", "seba/webapp/static"),
]

HIDDEN = [
    "seba.webapp.server",
    "seba.webapp.state",
    "seba.bundle",
    "seba.config",
    "seba.datamodel",
    "seba.engine",
    "seba.operators",
    "seba.net",
    "seba.stats",
    "seba.ratios",
    "seba.diagnosis",
    "seba.report",
    "seba.labels",
    "seba.intake",
    "seba.vec",
    "seba.shpio",
    "openpyxl",
    "docx",
    "PIL",
]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("先安装 PyInstaller：")
        print("  .venv\\Scripts\\python.exe -m pip install pyinstaller")
        return 2

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--name", NAME,
        "--console",
        "--collect-submodules", "seba",
        "--exclude-module", "scipy",
        "--exclude-module", "pyogrio",
        "--exclude-module", "shapely",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pytest",
    ]
    for mod in HIDDEN:
        cmd += ["--hidden-import", mod]
    for src, dst in ADD_DIRS:
        if os.path.exists(os.path.join(HERE, src)):
            cmd += ["--add-data", "%s%s%s" % (src, os.pathsep, dst)]
    cmd.append(os.path.join(HERE, "exe_main.py"))

    print("正在打包（首次约 2–5 分钟）……\n")
    rc = subprocess.call(cmd, cwd=HERE)
    if rc != 0:
        print("\n打包失败，退出码 %d" % rc)
        return rc

    exe = os.path.join(HERE, "dist", NAME + ".exe")
    if os.path.exists(exe):
        mb = os.path.getsize(exe) / 1048576
        print("\n" + "=" * 60)
        print("打包完成：%s" % exe)
        print("体积：%.1f MB" % mb)
        print("=" * 60)
        print("把这个 exe 发给别人，双击即可使用（无需装 Python）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
