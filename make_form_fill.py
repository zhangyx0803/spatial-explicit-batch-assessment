# -*- coding: utf-8 -*-
"""生成《软著登记表填写内容》，供在线表单逐字段照抄。"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = r"D:\上海师大\科研竞赛\软著申请\空间显式批量评估工作台系统"
OUT = os.path.join(ROOT, "01_申报材料", "软著登记表填写内容.docx")

doc = Document()
s = doc.sections[0]
s.page_width = Cm(21.0)
s.page_height = Cm(29.7)
s.top_margin = Cm(2.2)
s.bottom_margin = Cm(2.0)
s.left_margin = Cm(2.4)
s.right_margin = Cm(2.2)

st = doc.styles["Normal"]
st.font.name = "宋体"
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
st.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
st.paragraph_format.space_before = Pt(0)
st.paragraph_format.space_after = Pt(0)

BLUE = RGBColor(0x1F, 0x38, 0x64)


def _f(r, name="宋体", size=10.5, bold=False, color=None):
    r.font.name = name
    r.font.size = Pt(size)
    r.bold = bold
    if color is not None:
        r.font.color.rgb = color
    r._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    return r


def H(t):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.keep_with_next = True
    _f(p.add_run(t), "黑体", 13, True, BLUE)


def P(t, indent=True, bold=False, size=10.5):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(2)
    if indent:
        p.paragraph_format.first_line_indent = Pt(21)
    _f(p.add_run(t), "宋体", size, bold)
    return p


def BOX(t):
    """可直接复制的填写内容：浅底、等宽、不缩进。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(3)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.left_indent = Pt(14)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F2F5F8")
    pPr.append(shd)
    _f(p.add_run(t), "宋体", 10.5)
    return p


def LBL(t, n=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.keep_with_next = True
    txt = t if n is None else "%s（%d 字）" % (t, n)
    _f(p.add_run(txt), "黑体", 10.5, True)
    return p


def _shade(cell, color="DCE6F1"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    tcPr.append(shd)


def TBL(header, rows, widths, font=9.5):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        _f(p.add_run(h), "黑体", font, True)
        _shade(c)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            _f(p.add_run(v), "宋体", font)
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    return t


# ---------------- 封面标题 ----------------
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(6)
p.paragraph_format.space_after = Pt(2)
_f(p.add_run("软著登记表填写内容"), "黑体", 18, True, BLUE)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(10)
_f(p.add_run("空间显式批量评估工作台系统 V1.0"), "宋体", 11)

P("本表对应中国版权保护中心在线表单中“软件开发信息”与“软件功能与特点”两页。"
  "各字段后标注了表单的字数上限，框内文字可直接复制粘贴，字数已卡在上限之内。")

P("软件全称统一填写“空间显式批量评估工作台系统”，版本号统一填写“V1.0”，"
  "与软件说明书封面、源程序页眉逐字一致。")

# ---------------- 一 ----------------
H("一、开发的硬件环境")
LBL("开发的硬件环境", 48)
BOX("联想笔记本，Intel Core Ultra 9 285H，16核，32GB内存，1TB固态硬盘")

LBL("运行的硬件环境", 41)
BOX("x86台式机或笔记本，双核2.0GHz以上，4GB以上内存，500MB可用磁盘空间")

LBL("开发该软件的操作系统", 21)
BOX("Windows 11 家庭版 中文版 64位")

LBL("软件开发环境/开发工具", 46)
BOX("Python 3.12、Visual Studio Code、Git、PyInstaller")

P("开发硬件按实际使用的这台笔记本填写：联想 83L0 机型，处理器 Intel Core Ultra 9 285H，"
  "16 核 2.9GHz，内存 32GB，硬盘为 1TB 固态，显卡 NVIDIA RTX 5060 Laptop 8GB。"
  "该配置取自开发机实测，与运行环境一栏的最低配置要求不同：前者是研发所用机器，"
  "后者是用户机器需要满足的下限。")

# ---------------- 二 ----------------
H("二、运行平台与编程语言")
LBL("该软件的运行平台/操作系统", 27)
BOX("Windows 10 / Windows 11 64位")

LBL("软件运行支撑环境/支持软件", 47)
BOX("无需安装；Python运行时与依赖已打包进可执行文件；需Chrome或Edge浏览器查看结果。")

LBL("编程语言")
P("在语言按钮中勾选 Python，再勾选 JavaScript 与 HTML；"
  "“其他编程语言”补充填写 CSS。")
BOX("Python、JavaScript、HTML、CSS")

P("核心计算与数据处理为Python，前端界面为原生JavaScript与Canvas，"
  "样式表为独立CSS文件，四类语言均有实际代码对应。")

# ---------------- 三 ----------------
H("三、源程序量与软件描述")
LBL("源程序量")
P("填写 11122 行。该数字取自提交的源程序文档末行行号，与PDF内容一致，不要另行估算。")
BOX("11122")

LBL("开发目的", 50)
BOX("解决不动产批量评估中价格构成不可解释、无法按买方需求定制的问题，"
    "提供可追溯地理事实的估值与拆解工具。")

LBL("面向领域/行业", 38)
BOX("自然资源与不动产评估、房地产研究、金融机构押品估值、城市规划与地理信息应用。")

LBL("软件的主要功能", 200)
BOX("内置上海16个区、6132个小区的挂牌价与地理数据。可导入Shapefile、GeoJSON、"
    "Excel等格式并自动识别字段；以16个空间显式因子构建特征价格模型，批量输出估值、"
    "预测区间与残差；提供随机与空间分块交叉验证、COD、PRD、Moran I等精度检验；"
    "对单个地块局部拟合，用Shapley值把价格拆成逐项贡献并给置信区间；"
    "按支付意愿重算适配价；支持残差专题图、街道校准与离线HTML导出。")

# ---------------- 四 ----------------
H("四、鉴别材料")
TBL(
    ["页面项", "选择", "上传文件"],
    [
        ["文档鉴别材料", "一般交存",
         "空间显式批量评估工作台系统_V1.0_软件说明书.pdf"],
        ["源程序", "—",
         "空间显式批量评估工作台系统_V1.0_源程序.pdf"],
        ["其他相关证明文件", "留空", "不提交"],
    ],
    [4.2, 2.6, 9.0],
)

P("说明书共39页，不足60页，按一般交存规则应提交全部页，不要只截前后各30页。")
P("源程序共60页，页眉含软件名称与版本号，行号连续，前30页与后30页已覆盖全部代码。")
P("合作开发协议不作为软著必需材料提交，如审查环节另有要求再补充。")

# ---------------- 五 ----------------
H("五、容易出错的地方")
P("1. 软件全称与版本号必须与说明书、源程序逐字一致，写成“1.0”或“v1.0”是常见退回原因。")
P("2. 源程序量填写文档末行行号，而非按文件行数另行统计，两者口径不同。")
P("3. 著作权人为两位合作者时，登记表著作权人一栏须写全两位，与合作协议保持一致。")
P("4. 发表状态须与实际情况一致：代码仓库公开则填已发表，转为私有则改填未发表。")
P("5. 文档鉴别材料上传PDF，不要上传Word，也不要用截图拼接。")

out_dir = os.path.dirname(OUT)
os.makedirs(out_dir, exist_ok=True)
doc.save(OUT)
print("已生成：", OUT)
