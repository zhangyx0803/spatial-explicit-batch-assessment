# -*- coding: utf-8 -*-
"""中文词表：把内部代码翻译成不懂编程也能看懂的说法。

界面上一律显示中文，代码（英文标识）只在提示框里作为“技术标识”附注。
"""

from __future__ import annotations

from typing import Dict, List

__all__ = [
    "OP_CN", "PARAM_CN", "INPUT_CN", "MODE_CN", "STAT_CN",
    "LAYER_TYPE_CN", "FIELD_CN", "FACTOR_CN", "TEMPLATES",
    "factor_name", "op_name", "param_label", "catalog",
]

# 算子：名称 + 用途
OP_CN: Dict[str, Dict] = {
    "network_shortest_path": {"name": "路网最短路径", "desc": "算每个单元沿路网到目标设施的距离与用时"},
    "network_isochrone": {"name": "等时圈可达性", "desc": "按出行时间圈定范围，统计圈内设施数量"},
    "gravity_access": {"name": "重力可达性", "desc": "机会越多、距离越远衰减越大，累加得到的可达性指数"},
    "two_step_floating_catchment": {"name": "两步移动搜寻（2SFCA）", "desc": "同时考虑设施供给量与周边人口需求，常用于学校、医院"},
    "distance_decay": {"name": "距离衰减", "desc": "按衰减函数把距离换算成权重"},
    "buffer_overlay": {"name": "缓冲区统计", "desc": "统计指定半径内的设施数量或面积占比"},
    "spatial_join_agg": {"name": "空间连接聚合", "desc": "取到最近要素的距离等指标"},
    "kernel_density": {"name": "核密度估计", "desc": "设施的空间集聚强度"},
    "network_topology": {"name": "路网拓扑指标", "desc": "交叉口密度、尽端路比例等微观路网特征"},
    "raster_extract": {"name": "栅格取值", "desc": "按位置读取栅格图层的数值"},
    "attribute": {"name": "属性直读", "desc": "直接读取单元自带属性，不做空间运算"},
}

# 输入槽位
INPUT_CN: Dict[str, str] = {
    "network": "路网图层",
    "destinations": "目标设施",
    "origins": "起点",
    "supply": "供给设施",
    "demand": "需求字段",
    "dist": "距离来源",
    "opportunity": "机会点图层",
    "layer": "图层",
    "raster": "栅格图层",
    "field": "属性字段",
}

# 参数：中文名 + 单位 + 控件类型
PARAM_CN: Dict[str, Dict] = {
    "mode": {"name": "出行方式", "type": "select", "options": ["drive", "walk", "bike"]},
    "stat": {
        "name": "统计方式",
        "type": "select",
        "options": [
            "count", "weighted_count", "area_share",
            "nearest_distance", "intersection_density", "deadend_ratio", "mean",
        ],
    },
    "threshold_min": {"name": "时间阈值", "unit": "分钟", "type": "number", "step": 1},
    "thresholds_min": {"name": "时间阈值", "unit": "分钟", "type": "numbers"},
    "radius_m": {"name": "半径", "unit": "米", "type": "number", "step": 50},
    "bandwidth_m": {"name": "带宽", "unit": "米", "type": "number", "step": 50},
    "turn_penalty_min": {"name": "每次转向附加时间", "unit": "分钟", "type": "number", "step": 0.05},
    "mass": {"name": "机会总量", "unit": "", "type": "number", "step": 1},
    "impedance": {"name": "距离衰减方式", "type": "impedance"},
    "decay": {"name": "距离衰减方式", "type": "impedance"},
    "snap": {"name": "起终点吸附", "type": "snap"},
}

MODE_CN = {"drive": "驾车", "walk": "步行", "bike": "骑行"}
STAT_CN = {
    "count": "个数",
    "weighted_count": "加权个数",
    "area_share": "面积占比",
    "nearest_distance": "到最近要素距离",
    "intersection_density": "交叉口密度（个/km²）",
    "deadend_ratio": "尽端路比例",
    "mean": "取平均值",
}
IMPEDANCE_CN = {"exponential": "指数衰减", "power": "幂函数衰减", "gaussian": "高斯衰减"}

LAYER_TYPE_CN = {"network": "路网", "point": "点图层", "polygon": "面图层", "raster": "栅格"}

# 数据表字段
FIELD_CN: Dict[str, str] = {
    "unit_id": "单元编号",
    "price": "成交总价",
    "unit_price": "成交单价",
    "deal_date": "成交日期",
    "price_type": "价格类型",
    "source": "数据来源",
    "weight": "权重",
    "population": "常住人口",
    "pop_density": "人口密度",
    "area": "面积",
    "admin_code": "行政区",
    "use_type": "用途",
    "far": "容积率",
    "built_density": "建筑密度",
    "floor_ratio": "楼层比",
    "placebo_1": "对照变量甲",
    "placebo_2": "对照变量乙",
    "asof_date": "数据时点",
}

# 内置因子：中文名
FACTOR_CN: Dict[str, str] = {
    "net_cbd_dist": "到 CBD 路网距离",
    "acc_cbd_time": "到 CBD 车行时间",
    "acc_cbd_time_turn": "到 CBD 车行时间（含转向）",
    "acc_cbd_gravity": "到 CBD 重力可达性",
    "acc_metro_dist": "到最近地铁站步行距离",
    "acc_metro_cnt_15": "15 分钟地铁站数",
    "acc_school_2sfca": "教育资源可达性",
    "acc_hospital_2sfca": "医疗资源可达性",
    "acc_park_dist": "到最近公园距离",
    "acc_poi_com_1km": "1 公里商业网点数",
    "acc_retail_kde": "商业核密度",
    "env_green_500m": "500 米绿地率",
    "env_water_dist": "到最近水体距离",
    "env_noise_lnight": "夜间噪声",
    "net_intersect_dens": "交叉口密度",
    "net_deadend_ratio": "尽端路比例",
    "net_bus_cnt": "公交站点数",
    "unit_pop": "人口密度",
    "plan_far": "容积率",
    "built_density": "建筑密度",
    "floor_ratio": "楼层比",
    "b_placebo_1": "对照变量甲",
    "b_placebo_2": "对照变量乙",
}


def factor_name(code: str, note: str = "") -> str:
    """因子中文名：优先查词表，其次用配置里的中文备注，最后回落代码。

    备注里的括号说明（如“市级1.0/区级0.55/社区0.25”）是因子语义的一部分，
    不能截断成“中心地加权可达性（市级1.0/区”，界面与导出都保留完整名称。
    """
    if code in FACTOR_CN:
        return FACTOR_CN[code]
    if note:
        return note if len(note) <= 48 else note[:48]
    return code


def op_name(op: str) -> str:
    return OP_CN.get(op, {}).get("name", op)


def param_label(key: str) -> str:
    p = PARAM_CN.get(key)
    if not p:
        return key
    return p["name"] + ("（%s）" % p["unit"] if p.get("unit") else "")


# 新建因子用的中文模板

TEMPLATES: List[Dict] = [
    {
        "key": "facility_time",
        "name": "到某设施的路网时间",
        "desc": "算每个单元到指定设施（如 CBD、医院）的最短车行时间",
        "op": "network_shortest_path",
        "inputs": {"network": "network", "destinations": "point"},
        "output_field": "t_min",
        "params": {"mode": "drive", "snap": {"method": "nearest_node", "max_dist_m": 300}},
    },
    {
        "key": "facility_buffer_count",
        "name": "半径内设施数量",
        "desc": "统计单元周边指定半径内的设施个数，如 1 公里内商业网点",
        "op": "buffer_overlay",
        "inputs": {"layer": "point"},
        "output_field": "value",
        "params": {"radius_m": 1000, "stat": "count"},
    },
    {
        "key": "facility_nearest",
        "name": "到最近设施的距离",
        "desc": "算到最近公园、水体等要素的直线距离",
        "op": "spatial_join_agg",
        "inputs": {"layer": "point"},
        "output_field": "value",
        "params": {"stat": "nearest_distance"},
    },
    {
        "key": "facility_kde",
        "name": "设施核密度",
        "desc": "设施点越密集，取值越高，反映商业或公共服务集聚度",
        "op": "kernel_density",
        "inputs": {"layer": "point"},
        "output_field": "value",
        "params": {"bandwidth_m": 600},
    },
    {
        "key": "green_ratio",
        "name": "绿地覆盖率",
        "desc": "缓冲区内绿地面积占圆面积的比重",
        "op": "buffer_overlay",
        "inputs": {"layer": "polygon"},
        "output_field": "value",
        "params": {"radius_m": 500, "stat": "area_share"},
    },
    {
        "key": "raster_value",
        "name": "读取栅格数值",
        "desc": "按位置读取栅格图层（如噪声、人口）的数值",
        "op": "raster_extract",
        "inputs": {"raster": "raster"},
        "output_field": "value",
        "params": {"stat": "mean"},
    },
]


def catalog() -> Dict:
    """一次性把词表发给前端。"""
    return {
        "op": OP_CN,
        "input": INPUT_CN,
        "param": PARAM_CN,
        "mode": MODE_CN,
        "stat": STAT_CN,
        "impedance": IMPEDANCE_CN,
        "layer_type": LAYER_TYPE_CN,
        "field": FIELD_CN,
        "factor": FACTOR_CN,
        "templates": TEMPLATES,
    }
