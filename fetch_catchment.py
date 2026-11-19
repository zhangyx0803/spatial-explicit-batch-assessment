# -*- coding: utf-8 -*-
"""抓取并解析各区教育局「公办小学招生划片范围」页，输出 config/catchment/<区>.csv。

只访问政府公开页面（shanghai.gov.cn），不涉及商业网站。
"""
from __future__ import annotations

import csv
import html
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "config", "catchment")

# 已确认的官方页面（2025 年度）
PAGES = {
    "徐汇区": "https://cdn.shanghai.gov.cn/xhqywjy/20250411/c7624fb2664d407cb7a23d54210a1f22.html",
    "静安区": "https://cdn.shanghai.gov.cn/jaqywjy/20250407/942720b478bf4d73b62c28ee752e8795.html",
    "黄浦区": "https://cdn.shanghai.gov.cn/hpqywjy/20250416/e1823c7eac2a46af9a27036dc13f3715.html",
    "浦东新区": "https://www.shanghai.gov.cn/pdxqywjy/20250513/4f1a0398a0504eb7a77656d3f5c62c1b.html",
    "闵行区": "https://cdn.shanghai.gov.cn/mhqywjy/20250407/ed5004ce90194b3d8974000baa41c125.html",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEBA-research/1.0; academic use)",
}


class TableParser(HTMLParser):
    """把页面里的所有表格抽成 [[cell, ...], ...]。"""

    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
            self._depth += 1
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            if any(c for c in self._row):
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table":
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def pick_columns(rows):
    """在表头行里找「学校名」「对口范围」两列的下标。兼容多种写法。"""
    NAME_KEYS = ("学校名称", "校名", "学校", "校 名", "单位")
    SCOPE_KEYS = ("对口", "划片", "地段", "居委")
    for i, row in enumerate(rows[:8]):
        name_i = scope_i = cnt_i = None
        for j, c in enumerate(row):
            c2 = c.replace(" ", "").replace("\u3000", "")
            if name_i is None and any(k in c2 for k in NAME_KEYS):
                name_i = j
            if scope_i is None and any(k in c2 for k in SCOPE_KEYS):
                scope_i = j
            if cnt_i is None and ("班级" in c2 or "招生计划" in c2 or "招生数" in c2):
                cnt_i = j
        if name_i is not None and scope_i is not None:
            return i, name_i, scope_i, cnt_i
    return None


def parse_district(name: str, url: str):
    page = fetch(url)
    p = TableParser()
    p.feed(page)
    best = None
    best_score = -1
    for rows in p.tables:
        info = pick_columns(rows)
        if not info:
            continue
        hi, ni, ji, ci = info
        body = [r for r in rows[hi + 1:] if len(r) > max(ni, ji) and r[ni]]
        # 只保留看起来像学校的行，并按「对口文本总量」打分，避免选中汇总表
        body = [r for r in body if re.search(r"[学幼]", r[ni])]
        score = sum(len(r[ji]) for r in body)
        if body and score > best_score:
            best_score = score
            best = (info, body)
    if not best:
        return None, "未找到表格"
    (hi, ni, ji, ci), body = best
    out = []
    for r in body:
        school = re.sub(r"\s+", " ", r[ni]).strip()
        scope = r[ji].strip()
        if not school or not scope:
            continue
        cnt = r[ci].strip() if ci is not None and ci < len(r) else ""
        cnt = re.sub(r"[^0-9]", "", cnt)
        out.append({"学校名称": school, "招生班级数": cnt, "是否集团化": "",
                    "对口居委": scope})
    return out, None


def main() -> int:
    os.makedirs(OUTDIR, exist_ok=True)
    only = sys.argv[1:] or list(PAGES)
    for d in only:
        url = PAGES.get(d)
        if not url:
            print("%-6s 无已知页面" % d)
            continue
        try:
            rows, err = parse_district(d, url)
        except Exception as exc:
            print("%-6s 抓取失败：%s" % (d, exc))
            continue
        if not rows:
            print("%-6s 解析失败：%s" % (d, err))
            continue
        path = os.path.join(OUTDIR, d + ".csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["学校名称", "招生班级数", "是否集团化", "对口居委"])
            w.writeheader()
            w.writerows(rows)
        tot = sum(len(r["对口居委"]) for r in rows)
        print("%-6s %3d 所学校  对口文本 %5d 字  → %s" % (d, len(rows), tot, os.path.basename(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
