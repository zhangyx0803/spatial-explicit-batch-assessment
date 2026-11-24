# -*- coding: utf-8 -*-
"""空间显式批量评估工作台（SEBA）- 可运行版本。

模块划分与《实现方案 V1.0》第四章一致：

    config      声明式因子配置（YAML 子集解析）与校验
    datamodel   unit / attr / obs / layer 四张表的数据契约
    grid        内置测试场景生成
    net         CSR 稀疏图、Dijkstra、起终点吸附
    operators   空间算子库
    engine      因子计算引擎（DAG、拓扑排序、缓存）
    stats       回归、共线性、空间分块 CV、smearing
    ratios      比率研究（COD / PRD）
    diagnosis   残差空间自相关诊断与专题图
    report      XLSX / DOCX 成果输出
"""

__version__ = "1.0.0"
