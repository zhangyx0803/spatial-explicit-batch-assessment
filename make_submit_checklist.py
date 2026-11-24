# -*- coding: utf-8 -*-
"""生成《软著登记提交清单与申请表填写指引》。"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT_DIR = r"D:\上海师大\科研竞赛\软著申请\空间显式批量评估工作台系统\01_申报材料"
OUT = os.path.join(OUT_DIR, "软著登记提交清单与申请表填写指引.docx")
os.makedirs(OUT_DIR, exist_ok=True)

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

def P(t, indent=True, bold=False):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(2)
    if indent:
        p.paragraph_format.first_line_indent = Pt(21)
    _f(p.add_run(t), "宋体", 10.5, bold)
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
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        _f(p.add_run(h), "黑体", font, True)
        _shade(c)
    for row in rows:
        cs = t.add_row().cells
        for i, v in enumerate(row):
            cs[i].text = ""
            p = cs[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            _f(p.add_run(str(v)), "宋体", font)
    t.autofit = False
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
        for r in t.rows:
            r.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(3)

# ============================ 标题 ============================
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
_f(p.add_run("计算机软件著作权登记　提交清单与申请表填写指引"), "黑体", 16, True, BLUE)
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(12)
_f(p.add_run("空间显式批量评估工作台系统 V1.0"), "宋体", 11, False, RGBColor(0x55, 0x55, 0x55))

# ============================ 一、可行性 ============================
H("一、可行性结论")
P("可以申请。经核查，本软件的代码量、文档完备度与权利归属材料均满足登记要求，"
  "且不存在第三方代码或敏感信息混入的问题。需要特别注意的是发表状态的填写（见第三节）。")

TBL(["核查项", "要求", "实际情况", "判定"],
    [["源程序页数", "前、后各连续 30 页，共 60 页；每页不少于 50 行", "非空代码 11,089 行，约 222 页", "满足"],
     ["源程序纯度", "应为申请人自行开发，不含第三方库", "已剔除 vendor 目录与依赖包", "满足"],
     ["文档页数", "任一种文档；不足 60 页则全部提交", "软件说明书 37 页", "满足"],
     ["权利归属", "合作开发须有合作协议", "已签署合作开发协议", "满足"],
     ["身份证明", "各方身份证件", "双方身份证复印件", "待补"],
     ["敏感信息", "不得含密钥等", "已全库扫描，无 API Key", "满足"]],
    widths=[2.8, 6.4, 5.2, 1.8])

# ============================ 二、材料清单 ============================
H("二、提交材料清单")
TBL(["序号", "材料名称", "份数", "状态", "获取方式 / 文件位置"],
    [["1", "软件著作权登记申请表", "在线填写后打印 1 份", "待填", "中国版权保护中心官网在线填报系统"],
     ["2", "源程序鉴别材料", "1 份 60 页", "已生成", "01_申报材料\\...V1.0_源程序.docx（需转 PDF 上传）"],
     ["3", "文档鉴别材料", "1 份 37 页", "已有", "01_申报材料\\...V1.0_软件说明书.pdf"],
     ["4", "合作开发协议", "1 份（双方签字）", "已生成", "01_申报材料\\计算机软件合作开发协议.docx"],
     ["5", "合作方一身份证明", "身份证正反面复印件 1 份", "待补", "本人提供"],
     ["6", "合作方二身份证明", "身份证正反面复印件 1 份", "待补", "本人提供"],
     ["7", "代理委托书（如委托代理机构）", "1 份", "按需", "由代理机构提供模板"]],
    widths=[1.2, 5.4, 3.6, 2.0, 4.0])

P("说明：目前多数情形下采用线上登记，申请表在线填写、鉴别材料以 PDF 上传，"
  "纸质材料按系统提示邮寄或现场提交。具体以受理系统当期要求为准。", indent=True)

# ============================ 三、申请表填写 ============================
H("三、申请表关键字段填写建议")
TBL(["字段", "建议填写", "说明"],
    [["软件全称", "空间显式批量评估工作台系统", "须与源程序页眉、文档封面完全一致"],
     ["软件简称", "不填", "可填可不填；本套材料界面与文档均不再使用英文缩写"],
     ["版本号", "V1.0", "三处一致"],
     ["开发完成日期", "2026 年 11 月 18 日", "以首个可运行版本完成日为准"],
     ["发表状态", "已发表", "代码已在公开仓库发布，须据实填写"],
     ["首次发表日期", "2026 年 11 月 18 日", "与首次公开提交日一致"],
     ["开发方式", "合作开发", "与合作协议对应"],
     ["权利取得方式", "原始取得", "自行开发，非受让、非继承"],
     ["权利范围", "全部权利", "两人共同享有"],
     ["著作权人", "合作方一、合作方二（两人）", "登记为多个著作权人，不填份额"],
     ["软件分类", "应用软件", "-"],
     ["编程语言", "Python、JavaScript", "另有 HTML/CSS、YAML 配置"],
     ["源程序量", "11,089 行", "按非空行计"],
     ["开发硬件环境", "PC，双核 2.0 GHz 以上，内存 4 GB 以上", "-"],
     ["运行硬件环境", "同上", "-"],
     ["开发软件环境", "Windows 10/11，Python 3.10 及以上", "-"],
     ["运行软件环境", "Windows 10/11（64 位），现代浏览器", "无需安装 Python"],
     ["主要功能", "见下方说明", "控制在 200 字以内"],
     ["技术特点", "见下方说明", "控制在 200 字以内"]],
    widths=[3.4, 6.6, 6.2])

P("主要功能（可直接复制）：", bold=True)
P("以村级行政单元为评估单元，将路网、土地利用、商业设施、学校、轨道交通等地理数据"
  "转化为可解释的估价因子，通过特征价格模型完成不动产批量估值；提供精度检验、"
  "空间诊断与分区校准；可将估值结果拆解为逐项因素的价格贡献，并按使用者偏好重新加权，"
  "给出个性化适配价；支持多行政区切换、地图交互与成果导出。")

P("技术特点（可直接复制）：", bold=True)
P("空间显式：全部因子由真实地理数据计算，结果可追溯至所依赖的地理事实；"
  "可解释：采用特征价格回归，系数、贡献额与置信区间全部公开；"
  "可复现：因子计算带算子版本与参数校验，相同输入恒定输出；"
  "离线可用：可打包为单文件离线成果，无需服务器与网络。")

# ============================ 四、注意事项 ============================
H("四、注意事项")

P("1. 三处名称必须完全一致。", bold=True)
P("申请表、源程序页眉、文档封面上的软件全称与版本号须逐字相同，"
  "包括是否带系统二字、中间有无空格。本套材料统一为空间显式批量评估工作台系统 V1.0。")

P("2. 发表状态须据实填写。", bold=True)
P("本软件的源代码已推送至公开代码托管平台，构成著作权法意义上的发表。"
  "申请表中若填未发表而实际已公开，可能被要求补正。建议填已发表，"
  "首次发表日期取首次公开提交之日。若希望避免该问题，可先将仓库转为私有，"
  "但已公开的历史不影响此前已构成发表的事实。")

P("3. 源程序材料不得夹带第三方代码。", bold=True)
P("材料已剔除 vendor 目录下的第三方依赖，仅保留自行开发的 30 个源文件。"
  "如后续改动代码，需重新生成本材料。")

P("4. 合作开发协议须双方签字。", bold=True)
P("协议中已约定著作权由双方共同享有、登记为多个著作权人，与申请表的权利范围"
  "著作权人两栏相互对应。建议一式两份均手写签名，扫描后上传。")

P("5. 身份证件须在有效期内。", bold=True)
P("正反面复印或扫描在同一页，信息清晰可辨。")

P("6. 审查周期。", bold=True)
P("一般为受理后 30 至 60 个工作日，可申请加急。登记证书以电子形式发放。")

# ============================ 五、待补事项 ============================
H("五、尚需补充的事项")
TBL(["事项", "由谁提供", "说明"],
    [["双方姓名", "两位合作方", "填入协议与申请表"],
     ["双方身份证号", "两位合作方", "仅用于申请表，不写入协议"],
     ["双方联系方式", "两位合作方", "填入协议首部"],
     ["开发完成日期确认", "两位合作方", "建议取首个可运行版本完成日"],
     ["是否委托代理机构", "两位合作方", "自行办理可省代理费，但需熟悉流程"]],
    widths=[4.0, 4.4, 7.8])

doc.save(OUT)
print("已生成：%s" % OUT)
print("大小：%.1f KB" % (os.path.getsize(OUT) / 1024))
