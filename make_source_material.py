# -*- coding: utf-8 -*-
"""生成软著登记的“源程序鉴别材料”：前 30 页 + 后 30 页，每页 50 行。

格式要点（按中国版权保护中心通行要求）：
    · 页眉标注软件全称与版本号
    · 每页 50 行（不含空行），行首连续行号
    · 连续页码
    · 不含第三方库代码（vendor）、数据文件与本地配置
"""
import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = r"D:\上海师大\科研竞赛\软著申请\空间显式批量评估工作台系统\01_申报材料"
OUT = os.path.join(OUT_DIR, "空间显式批量评估工作台系统_V1.0_源程序.docx")

SW_NAME = "空间显式批量评估工作台系统"
SW_VER = "V1.0"
PAGE_LINES = 50
N_PAGES_EACH = 30

ROOTS = ["seba", "config"]
EXTS = (".py", ".js", ".css", ".html", ".yaml")
SKIP_DIRS = ("vendor", "__pycache__", ".venv", "data", "dist", "build", "out")

ORDER_HINT = [
    "seba/__init__.py", "seba/config.py", "seba/datamodel.py", "seba/grid.py",
    "seba/shpio.py", "seba/vec.py", "seba/net.py", "seba/operators.py",
    "seba/engine.py", "seba/stats.py", "seba/diagnosis.py", "seba/centralplace.py",
    "seba/realdata.py", "seba/intake.py", "seba/importer.py", "seba/bundle.py",
    "seba/labels.py", "seba/report.py", "seba/decompose.py",
    "seba/webapp/__init__.py", "seba/webapp/state.py", "seba/webapp/server.py",
    "seba/webapp/static/index.html", "seba/webapp/static/style.css",
    "seba/webapp/static/app.js", "seba/webapp/static/intake.js",
    "seba/webapp/static/tour.js",
    "config/factors.yaml", "config/factors_real.yaml",
]


def collect():
    """按逻辑顺序收集代码行（剔除空行与第三方目录）。"""
    files = []
    for root in ROOTS:
        base = os.path.join(HERE, root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith(EXTS):
                    rel = os.path.relpath(os.path.join(dirpath, fn), HERE).replace("\\", "/")
                    files.append(rel)

    def key(p):
        return (0, ORDER_HINT.index(p)) if p in ORDER_HINT else (1, p)

    files = sorted(set(files), key=key)

    lines = []
    for rel in files:
        try:
            txt = open(os.path.join(HERE, rel), encoding="utf-8").read().split("\n")
        except Exception:
            continue
        lines.append("#" * 3 + " 文件：" + rel + " " + "#" * 3)
        for t in txt:
            t = t.replace("\t", "    ").rstrip()
            if t.strip():
                lines.append(t)
    return files, lines


def setup(wid):
    s = wid.sections[0]
    # 横向 A4：源代码行较长，纵向 8pt 会大量折行，导致 60 页变成 61 页
    s.page_width = Cm(29.7)
    s.page_height = Cm(21.0)
    s.top_margin = Cm(1.2)
    s.bottom_margin = Cm(1.1)
    s.left_margin = Cm(1.0)
    s.right_margin = Cm(1.0)
    s.header_distance = Cm(0.8)

    st = wid.styles["Normal"]
    st.font.name = "Consolas"
    st.font.size = Pt(6)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = st.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(9.6)

    hp = s.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run("%s %s" % (SW_NAME, SW_VER))
    hr.font.name = "宋体"
    hr.font.size = Pt(9)
    hr._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def emit(wid, lines, start_no):
    n = len(lines)
    no = start_no
    for i, text in enumerate(lines):
        p = wid.add_paragraph()
        r = p.add_run("%6d  %s" % (no, text))
        r.font.name = "Consolas"
        r.font.size = Pt(8)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
        no += 1
        if (i + 1) % PAGE_LINES == 0 and (i + 1) < n:
            p.add_run().add_break(WD_BREAK.PAGE)
    return no


def main() -> int:
    files, lines = collect()
    n = len(lines)
    need = PAGE_LINES * N_PAGES_EACH
    head = lines[:need]
    tail = lines[-need:]
    print("收录 %d 个文件，非空行 %d 行（约 %.0f 页 / 每页 %d 行）"
          % (len(files), n, n / PAGE_LINES, PAGE_LINES))
    print("取前 %d 行 + 后 %d 行 → %d 页" % (len(head), len(tail), 2 * N_PAGES_EACH))
    if n < need * 2:
        print("⚠ 不足 %d 行，应提交全部源码" % (need * 2))

    doc = Document()
    setup(doc)
    end1 = emit(doc, head, 1)
    # 前 1500 行正好排满 30 页，下一行自然从第 31 页开始；
    # 这里不再手动加页码分隔，否则会多出一张空白页（31 + 30 = 61 页）。
    emit(doc, tail, n - need + 1 if n >= need else len(head) + 1)

    doc.save(OUT)
    print("已生成：%s" % OUT)
    print("大小：%.1f KB" % (os.path.getsize(OUT) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
