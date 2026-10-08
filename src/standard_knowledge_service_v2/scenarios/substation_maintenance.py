from __future__ import annotations

from .models import ProtocolCapability, ScenarioDefinition, ScenarioParameter, StateTransition


class SubstationMaintenanceScenario:
    definition = ScenarioDefinition(
        name="substation_maintenance",
        aliases=["变电站设备运维", "变电站运维", "设备运维", "设备检修", "状态检修", "变电设备巡检"],
        required_parameters=["device_id", "device_type", "operating_state"],
        allowed_actions=["inspect", "test", "maintain", "alarm", "isolate", "trip", "close", "lockout", "reset"],
        safety_level="high",
        standard_topics=["设备巡视", "状态监测", "预防性试验", "检修安全", "倒闸操作", "缺陷与告警管理"],
        device_types=["电力变压器", "主变压器", "断路器", "隔离开关", "互感器", "避雷器", "母线", "继电保护装置"],
        parameters=[
            ScenarioParameter("device_id", "设备编号", required=True),
            ScenarioParameter("device_type", "设备类型", required=True),
            ScenarioParameter("operating_state", "运行状态", required=True),
            ScenarioParameter("temperature", "设备温度", "number", "℃"),
            ScenarioParameter("load_rate", "负载率", "number", "%"),
            ScenarioParameter("defect_level", "缺陷等级"),
        ],
        operating_states=["运行", "备用", "停运", "检修", "试验", "异常", "故障"],
        trigger_events=["温度异常", "油位异常", "气体告警", "绝缘异常", "例行巡视", "检修计划"],
        state_transitions=[
            StateTransition("运行", "严重缺陷", "异常", "alarm"),
            StateTransition("异常", "需要停电检修", "检修", "isolate"),
            StateTransition("检修", "验收合格", "备用", "reset"),
        ],
        protocol_capabilities=[
            ProtocolCapability("IEC61850", ("alarm", "isolate", "trip", "close", "lockout", "reset"), ("device_id", "logical_node", "data_object"), ("YPTR", "XCBR", "CSWI", "PTRC")),
            ProtocolCapability("Modbus", ("alarm", "isolate", "trip", "close", "lockout", "reset"), ("device_id", "slave_id", "coil_address")),
        ],
        risk_controls=["检修前核对停电范围与安全措施", "跳合闸和闭锁操作必须人工确认", "巡视和试验动作不得转换为控制帧"],
    )

    @property
    def scenario_name(self) -> str:
        return self.definition.name
