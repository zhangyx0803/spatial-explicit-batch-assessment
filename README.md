---
title: 空间显式批量评估工作台
emoji: 🏙️
colorFrom: indigo
colorTo: orange
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 用真实路网与 POI 做住宅批量估值，可视化可追溯
---

# 空间显式批量评估工作台系统 V1.0

**Spatial Explicit Batch Assessment**｜空间显式批量评估

一个把**真实地理数据**（路网、地铁、POI、土地利用、行政边界）变成**住宅批量估值**的可视化工具。
纯 Python 标准库 + numpy/pandas，无需 GDAL、无需数据库，一条命令起服务。

---

## 在线体验

部署后访问域名即可，无需安装任何东西。

> 当前部署在 Hugging Face Spaces：`https://zhangyx0803-<space名>.hf.space`
> 免费实例 48 小时无访问会休眠，首次打开约需 30 秒唤醒。

```bash
# 克隆
git clone https://github.com/zhangyx0803/spatial-explicit-batch-assessment.git
cd spatial-explicit-batch-assessment
```

本地跑（只需要 5 个 Python 包，不要 GDAL、不要数据库）：

```bash
pip install -r requirements.txt
python check_env.py                                  # 环境自检
python run_web.py --no-open --bundle data/demo_xuhui.bundle
# 打开 http://127.0.0.1:8765
```

---

## 它能做什么

| 能力 | 说明 |
|---|---|
| **批量估值** | 一次给几百到几千个村/居委单元出价，带 P10–P90 区间 |
| **因子可追溯** | 每个价格能追到依赖哪条路、哪个地铁站、哪块地 |
| **自动诊断** | 过拟合（空间块 CV）、系统偏差（PRD）、空间自相关（Moran's I）、失配片区 |
| **数据可换** | 上传自己的 Shapefile/GeoJSON/KML/GDB/Excel，系统自动识别字段 |
| **三种出图方式** | 村居面分级设色 / 六边形网格 / 质心点 |

内置数据：**上海 16 个区、7,255 个空间单元，其中 5,158 个为住宅单元、4,567 个有住宅价格**。

---

## 地图怎么看

- **面状填色**：每个村/居委按估值上色，暖色（深红）价格高，米白价格低
- **深灰细线**：真实路网（10,605 段主干与次干道路）
- **浅蓝区块**：水体（黄浦江、苏州河）
- **圆点**：识别出的商业中心地 —— 深红=市级、橙=区级、蓝=社区级
- 底部图例标注了以上全部符号

三种显示方式可在左侧「显示图层」切换：

| 方式 | 适用 | 特点 |
|---|---|---|
| 村居面 | 区级分析 | 忠于行政边界，可逐块核对 |
| 六边形网格 | 全市/跨区比较 | 等面积，消除单元大小差异 |
| 质心点 | 极密集小单元 | 最轻量 |

---

## 上传自己的数据

点顶部 **「接入数据」**：

1. 拖入文件（`.shp`+`.dbf`+`.prj` / `.geojson` / `.kml` / `.gdb` / `.csv` / `.xlsx`）
2. 系统自动识别文件类型与字段含义，并给出置信度
3. 核对下拉框（可手动改）
4. 点「确认」，**立刻用你的数据跑完并出图**，不需要重启

### 自动识别怎么做到的

两条判据缺一不可：

- **字段名语义**：中英文同义词库（`fclass` / `道路等级` / `ROAD_TYPE` / `grade` 都认）
- **取值形态**：`motorway/trunk/primary` 或 `高速/国道/主干路` → 道路等级；`F/T/B` → 单行标志

所以**字段名完全无意义也能认**：`FIELD_1/FIELD_2/FIELD_3` 三个列，靠取值也能识别出哪个是道路等级、哪个是单行标志。

### 缺数据会自动降级

只传评估单元边界也能跑：路网用规则格网近似，缺土地利用就停用绿地/建设用地因子，并在报告里写明缺了什么、影响了什么。

---

## 本地开发

```bash
# 内置数据（14 个区为小区级真实挂牌价，无需任何外部数据）
python run_web.py

# 真实数据（需要上海村界/路网/土地利用/OSM GDB）
python run_web.py --real 徐汇区

# 全市
python run_web.py --real 全市

# 打包成可分发数据集
python run_web.py --export-bundle data/demo_xuhui.bundle --real 徐汇区
```

换城市：编辑 `config/datasource.json`（参考 `config/datasource.example.json`），路径与字段名都可配，代码不用改。

---

## 目录结构

```
spatial-explicit-batch-assessment/
├── run_web.py        启动入口（支持 --bundle / --real / --export-bundle）
├── check_env.py      部署前环境自检
├── data/
│   └── demo_xuhui.bundle   预打包数据集（880 KB，含因子结果与底图）
├── config/
│   ├── factors.yaml        演示场景因子配置
│   ├── factors_real.yaml   真实数据因子配置
│   └── datasource.example.json  换城市的模板
└── seba/
    ├── net.py            CSR 图 + Dijkstra（scipy 可选加速）
    ├── operators.py      11 个空间算子（最短路/等时圈/2SFCA/核密度…）
    ├── engine.py         因子 DAG 引擎（拓扑排序 + 缓存）
    ├── centralplace.py   中心地识别与分级加权可达性
    ├── vec.py            统一矢量读取（shp/geojson/kml/gdb）
    ├── intake.py         字段语义自动识别
    ├── realdata.py       真实数据装配
    ├── bundle.py         数据集打包与加载
    ├── stats.py / ratios.py / diagnosis.py
    ├── report.py         Excel + DOCX 输出
    └── webapp/           标准库 http.server + 原生 JS
```

---

## 依赖说明

| 依赖 | 用途 | 必需 |
|---|---|---|
| numpy, pandas | 计算与数据表 | ✅ |
| openpyxl, python-docx, Pillow | 导出 Excel/Word/PNG | ✅ |
| scipy | 批量最短路加速（约 12×） | 可选 |
| pyogrio, shapely | 读取 FileGDB | 可选 |

不装可选项时，程序自动走纯 Python 实现，功能不缺，只是慢一些。

---

## 已知限制

- 价格：14 个区使用小区级真实挂牌价（6,132 个小区按 800 米聚合）；崇明、金山两区因小区稀疏仍用合成价
- 真实价格下各区训练 R² 为 0.31–0.82，明显低于合成数据时期的 0.72–0.90——楼层、朝向、装修、房龄等未纳入模型的信息仍占很大比重
- 学区：对口划片表目前只取到徐汇、静安、黄浦、浦东、闵行五区；招生班级数与集团化属性仅静安公布，其余区自动剔除
- 分区 COD 多在 5–9（低于 IAAO 的 15 标准）；黄浦、奉贤、杨浦三区空间分块交叉验证为负，说明空间外推能力不足
