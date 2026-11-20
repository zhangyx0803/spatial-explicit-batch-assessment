# -*- coding: utf-8 -*-
"""成果输出：XLSX 明细表 + DOCX 校准报告。

报告直接生成 DOCX（python-docx），不经过 markdown → PDF 的转换链：
中文字体、表格宽度与负号显示都更可控，也少一个出错环节。
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np

__all__ = ["write_workbook", "write_calibration_report"]


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------

def write_workbook(path: str, sheets: Dict[str, "object"]) -> str:
    import pandas as pd

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
    return path


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

def _set_cell(cell, text, bold=False, size=8.5, align_center=False):
    from docx.shared import Pt

    cell.text = ""
    p = cell.paragraphs[0]
    if align_center:
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(str(text))
    r.font.size = Pt(size)
    r.bold = bold
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)


def _add_table(doc, header: Sequence[str], rows: Sequence[Sequence], widths=None):
    from docx.shared import Inches

    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.autofit = False
    for i, h in enumerate(header):
        _set_cell(t.rows[0].cells[i], h, bold=True, align_center=True)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            _set_cell(cells[i], v)
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    return t


def _kv_table(doc, pairs: Sequence[tuple]):
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in pairs:
        cells = t.add_row().cells
        _set_cell(cells[0], k, bold=True)
        _set_cell(cells[1], v)
    return t


def write_calibration_report(path: str, ctx: Dict) -> str:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(10.5)

    h = doc.add_heading("空间显式批量评估工作台系统 V1.0", level=0)
    doc.add_paragraph("批量估值校准报告").runs[0].bold = True

    # 1 数据概况
    doc.add_heading("1  数据概况", level=1)
    _kv_table(
        doc,
        [
            ("研究区", ctx["project_name"]),
            ("坐标系", ctx["crs"]),
            ("评估单元数", format(ctx["n_units"], ",")),
            ("成交样本数", format(ctx["n_obs"], ",")),
            ("数据时点", ctx["asof_date"]),
            ("单元面积", "%.0f m²" % ctx["cell_area"]),
            ("吸附失败率", "—" if ctx.get("snap_failed") is None
             else "%.2f%%" % (ctx["snap_failed"] * 100)),
            ("平均吸附距离", "—" if ctx.get("snap_mean_dist") is None
             else "%.1f m" % ctx["snap_mean_dist"]),
        ],
    )

    # 2 因子清单
    doc.add_heading("2  因子清单与地理含义", level=1)
    doc.add_paragraph("共 %d 个因子进入模型，全部由声明式配置生成。" % len(ctx["factor_rows"]))
    _add_table(doc, ["因子编码", "算子", "含义", "均值", "标准差"], ctx["factor_rows"],
               widths=[1.15, 1.45, 1.85, 0.65, 0.65])

    # 3 模型参数
    doc.add_heading("3  模型参数（OLS，含对数变换与 smearing 修正）", level=1)
    doc.add_paragraph(
        "因变量取 ln(单价)；反变换使用 Duan smearing 因子 %.4f，"
        "避免直接 exp() 造成系统性低估。" % ctx["smearing"]
    )
    _add_table(doc, ["变量", "系数", "标准误", "t", "p", "显著性"], ctx["coef_rows"],
               widths=[1.30, 0.72, 0.68, 0.58, 0.55, 0.55])

    doc.add_heading("3.1  共线性诊断（VIF）", level=2)
    doc.add_paragraph(
        "VIF 超过 %s 的变量给出剔除建议。" % ctx["vif_threshold"]
    )
    _add_table(doc, ["变量", "R²（对其余变量）", "VIF"], ctx["vif_rows"],
               widths=[1.55, 1.20, 0.85])

    # 4 精度
    doc.add_heading("4  精度指标", level=1)
    doc.add_paragraph(
        "随机 K 折会因空间自相关高估精度；空间分块 CV 整块留出，更接近真实部署误差。"
    )
    metric_rows = [
        [r[0], "%.4f" % r[1], "%.4f" % r[2], "%.4f" % r[3], "%.2f" % r[4], "%.2f" % r[5]]
        for r in ctx["metric_rows"]
    ]
    _add_table(
        doc,
        ["口径", "R²", "RMSE(log)", "MAE(log)", "MAPE(%)", "中位APE(%)"],
        metric_rows,
        widths=[1.05, 0.72, 0.78, 0.76, 0.72, 0.80],
    )

    # 5 比率研究
    doc.add_heading("5  比率研究（IAAO 口径）", level=1)
    _kv_table(
        doc,
        [
            ("样本量", format(int(ctx["ratio"]["n"]), ",")),
            ("中位比率", "%.4f" % ctx["ratio"]["median_ratio"]),
            ("算术平均比率", "%.4f" % ctx["ratio"]["mean_ratio"]),
            ("COD", "%.2f（阈值 ≤ %.0f，%s）" % (
                ctx["ratio"]["cod"], ctx["ratio"]["cod_max"],
                "通过" if ctx["ratio"]["cod_ok"] > 0 else "未通过")),
            ("PRD", "%.4f（区间 %.2f–%.2f，%s）" % (
                ctx["ratio"]["prd"], ctx["ratio"]["prd_low"], ctx["ratio"]["prd_high"],
                "通过" if ctx["ratio"]["prd_ok"] > 0 else "未通过")),
        ],
    )
    doc.add_paragraph(
        "口径说明：COD 的分子是各比率与中位数比率之绝对偏差的算术平均，"
        "不做 0.6745 换算；比率基于空间分块 CV 的留块预测，为样本外口径。"
    )

    # 6 空间诊断
    doc.add_heading("6  空间误差诊断", level=1)
    _kv_table(
        doc,
        [
            ("全局 Moran's I", "%.4f" % ctx["moran"].i),
            ("期望值 E[I]", "%.4f" % ctx["moran"].e_i),
            ("置换标准差", "%.4f" % ctx["moran"].sd),
            ("z 值", "%.3f" % ctx["moran"].z),
            ("置换检验 p 值", "%.4f（%d 次置换）" % (ctx["moran"].p, ctx["moran"].n_perm)),
            ("结论", ctx["moran"].verdict()),
        ],
    )
    doc.add_paragraph("残差专题图见同目录 residual_map.png。")
    doc.add_heading("6.1  系统性失配板块", level=2)
    _add_table(doc, ["行政单元", "残差均值", "单元数", "判定"], ctx["district_rows"],
               widths=[0.90, 0.90, 0.70, 1.20])

    # 7 复现标识
    doc.add_heading("7  复现标识", level=1)
    _kv_table(
        doc,
        [
            ("run_id", ctx["run_id"]),
            ("配置指纹", ctx["config_fingerprint"]),
            ("随机种子", str(ctx["seed"])),
            ("数据版本", ctx["data_version"]),
            ("引擎版本", ctx["engine_version"]),
            ("数据性质", ctx.get("data_nature") or "见数据来源说明"),
        ],
    )

    doc.save(path)
    return path
