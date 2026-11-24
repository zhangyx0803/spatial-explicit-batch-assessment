# -*- coding: utf-8 -*-
"""生成《计算机软件合作开发协议》精简版。

相较上一版：
    1. 删除身份证号栏（著作权登记时另附）
    2. 费用条款改为共同费用双方平均分担
    3. 由 13 条压缩为 10 条，约 3 页
    4. 删除附件，模块清单并入正文
"""
import os

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

OUT_DIR = r"D:\上海师大\科研竞赛\软著申请\空间显式批量评估工作台系统\01_申报材料"
OUT = os.path.join(OUT_DIR, "计算机软件合作开发协议.docx")
os.makedirs(OUT_DIR, exist_ok=True)

doc = Document()
sec = doc.sections[0]
sec.page_width = Cm(20.9)
sec.page_height = Cm(29.6)
sec.top_margin = Cm(2.4)
sec.bottom_margin = Cm(2.4)
sec.left_margin = Cm(3.0)
sec.right_margin = Cm(3.0)

n = doc.styles["Normal"]
n.font.name = "宋体"
n.font.size = Pt(10.5)
n.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
n.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
n.paragraph_format.line_spacing = Pt(19)

def _f(run, name="宋体", size=10.5, bold=False):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    return run

def TITLE(t):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(16)
    _f(p.add_run(t), "黑体", 17)

def H(t):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    _f(p.add_run(t), "黑体", 11.5, True)

def P(t, prefix=None, indent=True):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(1)
    if indent:
        p.paragraph_format.first_line_indent = Pt(21)
    if prefix:
        _f(p.add_run(prefix), "宋体", 10.5, True)
    _f(p.add_run(t), "宋体", 10.5)
    return p

def PLAIN(t, size=10.5):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    _f(p.add_run(t), "宋体", size)
    return p

# ============================ 首部 ============================
TITLE("计算机软件合作开发协议")

P("合作方一（自然人）", indent=False)
PLAIN("　　姓　　名：　　　　　　　　　联系方式：")
doc.add_paragraph().paragraph_format.space_after = Pt(2)
P("合作方二（自然人）", indent=False)
PLAIN("　　姓　　名：　　　　　　　　　联系方式：")

doc.add_paragraph()
P("合作方一与合作方二基于共同的学术兴趣与专业分工，自愿共同开发本协议项下的计算机软件。"
  "双方系平等的合作开发者，不存在委托与受托关系。为明确双方权利义务，依据"
  "《中华人民共和国民法典》及相关法律法规，本着平等自愿、诚实信用、协商一致的原则，"
  "订立本协议。")

# ============================ 第一条 ============================
H("第一条　开发内容")
P("软件名称：空间显式批量评估工作台系统　V1.0；英文名称：Spatial Explicit Batch "
  "Assessment（缩写 SEBA）。", prefix="1.1　")
P("软件目标：本软件是一套面向不动产批量评估与价格构成分析的空间决策工具。软件以村级"
  "行政单元为评估单元，将路网、土地利用、商业设施、学校、轨道交通站点等地理数据转化为"
  "可解释的估价因子，通过特征价格模型完成批量估值；并在此基础上把估值结果拆解为逐项"
  "因素的价格贡献，按使用者需求重新加权，给出个性化适配价。", prefix="1.2　")
P("主要模块：数据接入与字段识别、空间显式因子计算、批量估值与精度检验、空间诊断与分区"
  "校准、价格拆解与个性化适配、地图可视化与交互、行政区切换与成果导出。", prefix="1.3　")
P("开发语言与运行环境：Python 3.10 及以上；以本地可执行程序与本地网页界面方式运行，"
  "不依赖外部服务器。", prefix="1.4　")

# ============================ 第二条 ============================
H("第二条　合作方式与分工")
P("双方系平等的合作开发者，共同参与需求分析、方案设计、程序编写、测试与文档撰写，"
  "对本软件共同享有权利、共同承担开发工作。任何一方均非另一方的委托人或受托人。",
  prefix="2.1　")
P("双方分工如下，并可根据开发进展协商调整。", prefix="2.2　")
P("负责总体技术方案与因子体系设计；空间算子（网络最短路、等时圈、重力可达性、"
  "核密度、栅格提取等）的实现与校核；特征价格模型的估计、交叉验证与精度检验；"
  "空间诊断与分区校准；价格拆解算法（Shapley 分解与 Bootstrap 区间）的设计与实现。",
  prefix="合作方一：")
P("负责数据接入与字段自动识别、多源地理数据的清洗与坐标校核；可视化界面与地图交互功能的"
  "前端实现；行政区切换、成果导出与离线网页的生成；软件测试、用户操作手册与技术文档的"
  "撰写；著作权登记材料的整理与提交。", prefix="合作方二：")
P("下列事项可经双方协商决定：技术路线与整体架构的调整；著作权登记的名称、版本与署名顺序；"
  "对外发表、演示或参赛；向第三方许可或转让；分工内容的具体调整。", prefix="2.3　")
P("任何一方拟退出的，应提前三十日书面告知另一方，并就已完成成果的归属、后续维护及"
  "著作权登记等事项协商处理。未经另一方书面同意，任何一方不得将整体开发工作转由"
  "第三方完成。", prefix="2.4　")

# ============================ 第三条 ============================
H("第三条　进度、交付与验收")
P("开发起止时间：自 2026 年 7 月 1 日起至 2026 年 11 月 30 日止；双方可书面顺延。",
  prefix="3.1　")
P("交付内容：源代码、可执行程序、技术文档、用户操作手册及测试记录，以电子文件形式提交，"
  "双方各持一份。", prefix="3.2　")
P("验收标准：功能与第一条所述一致；在约定环境下可正常启动运行；主要功能经双方共同测试"
  "通过；文档齐备且与实际功能相符。", prefix="3.3　")
P("验收方式：由双方共同测试，确认功能符合 3.3 所列标准的，即视为验收通过，"
  "不另行签署验收文件。验收仅确认技术成果的完成状态，不涉及款项支付。", prefix="3.4　")

# ============================ 第四条 ============================
H("第四条　知识产权")
P("本软件的著作权由双方共同享有，双方均为该软件的著作权人。著作权登记以双方名义共同"
  "申请，登记为多个著作权人。", prefix="4.1　")
P("双方共同署名，署名顺序由双方协商确定并记载于登记材料；任何一方不得单方变更或删除"
  "他方署名。", prefix="4.2　")
P("向第三方许可使用、转让著作权或就此设定负担，应经双方协商一致并出具书面文件；"
  "任何一方不得擅自单独实施。", prefix="4.3　")
P("任何一方均可为其自身教学、科研或业务需要自行使用本软件，无需经另一方同意，"
  "亦无需支付费用。", prefix="4.4　")
P("软件中如使用第三方开源组件或数据，应遵守其许可条件，由引入方负责合规并告知另一方。"
  "本软件著作权的归属不因任何一方工作单位或身份变化而改变。", prefix="4.5　")

# ============================ 第五条 ============================
H("第五条　费用")
P("本项目为双方自愿的合作开发，双方之间不支付开发报酬，不涉及合同价款、标的金额或"
  "其他形式的对价。", prefix="5.1　")
P("开发过程中为本项目发生的共同费用（包括但不限于数据采购、接口调用、设备与场地、"
  "差旅等），由双方平均分担；单笔金额较大的支出，应经双方事先协商确认后发生。"
  "各自非为本项目发生的开支由本方自行承担。", prefix="5.2　")
P("本协议不设违约金条款，任何一方不得依据本协议向另一方主张违约金或赔偿金。",
  prefix="5.3　")

# ============================ 第六条 ============================
H("第六条　保密")
P("双方在合作中知悉的对方技术信息、数据资料及其他未公开信息均属保密信息，仅可用于"
  "履行本协议，不得向第三方披露或用于与本项目无关的用途。", prefix="6.1　")
P("下列情形不属于保密信息：接收方在披露前已合法知悉的；已进入公有领域的；从有权披露的"
  "第三方合法取得的；依法律规定或有权机关要求必须披露的。", prefix="6.2　")
P("保密义务自本协议签订之日起生效，在本协议终止后继续有效五年。本协议不含竞业限制，"
  "双方在合作之外的工作与研究方向不受限制。", prefix="6.3　")

# ============================ 第七条 ============================
H("第七条　不可抗力")
P("因不可抗力致使本协议全部或部分不能履行的，受影响一方可相应免除责任，但应在合理期限"
  "内书面告知另一方。不可抗力消除后，双方应协商恢复履行。", prefix="7.1　")

# ============================ 第八条 ============================
H("第八条　生效、变更与终止")
P("本协议自双方签字之日起生效。变更或补充应由双方另行签订书面文件，口头约定不发生效力。",
  prefix="8.1　")
P("双方协商一致、开发工作完成并经确认、或一方依 2.4 退出且后续事项处理完毕的，"
  "本协议终止。", prefix="8.2　")
P("本协议终止不影响第四条（知识产权）与第六条（保密）的效力。", prefix="8.3　")

# ============================ 第九条 ============================
H("第九条　争议解决")
P("因本协议引起的争议，双方应首先通过友好协商解决；协商期间，除争议事项外，"
  "双方应继续履行本协议其他条款。", prefix="9.1　")

# ============================ 第十条 ============================
H("第十条　其他")
P("本协议未尽事宜，由双方协商后以书面形式补充，补充文件与本协议具有同等效力；"
  "双方的通知与文件往来可通过书面或电子邮件等方式进行。", prefix="10.1　")
P("本协议一式两份，双方各执一份，具有同等效力。", prefix="10.2　")

# ============================ 签署 ============================
doc.add_paragraph()
doc.add_paragraph()
t = doc.add_table(rows=1, cols=2)
t.alignment = WD_TABLE_ALIGNMENT.CENTER
t.autofit = False
for i in range(2):
    t.columns[i].width = Cm(6.8)
for cell, who in zip(t.rows[0].cells, ("合作方一", "合作方二")):
    cell.text = ""
    _f(cell.paragraphs[0].add_run("%s（签字）" % who), "宋体", 10.5)
    for _ in range(3):
        cell.add_paragraph()
    _f(cell.add_paragraph().add_run("日　　期：　　　年　　月　　日"), "宋体", 10.5)

# 签名栏不要边框
from docx.oxml import OxmlElement  # noqa: E402

_tblPr = t._tbl.tblPr
_bd = OxmlElement("w:tblBorders")
for _e in ("top", "left", "bottom", "right", "insideH", "insideV"):
    _el = OxmlElement("w:" + _e)
    _el.set(qn("w:val"), "none")
    _el.set(qn("w:sz"), "0")
    _el.set(qn("w:space"), "0")
    _bd.append(_el)
_tblPr.append(_bd)

doc.save(OUT)
print("已生成：%s" % OUT)
print("大小：%.1f KB" % (os.path.getsize(OUT) / 1024))
