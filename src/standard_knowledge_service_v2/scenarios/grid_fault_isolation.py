from __future__ import annotations

from .models import ProtocolCapability, ScenarioDefinition, ScenarioParameter, StateTransition


class GridFaultIsolationScenario:
    definition = ScenarioDefinition(
        name="grid_fault_isolation",
        aliases=["电网故障隔离", "故障隔离", "故障切除", "故障处置", "保护动作", "事故处理"],
        required_parameters=["device_id", "fault_type", "fault_location", "operating_state"],
        allowed_actions=["alarm", "trip", "isolate", "lockout", "close", "reset", "restore_power"],
        safety_level="critical",
        standard_topics=["继电保护", "故障定位", "选择性切除", "失灵保护", "自动重合闸", "供电恢复"],
        device_types=["线路", "母线", "电力变压器", "断路器", "继电保护装置", "配电自动化终端"],
        parameters=[
            ScenarioParameter("device_id", "故障设备编号", required=True),
            ScenarioParameter("fault_type", "故障类型", required=True),
            ScenarioParameter("fault_location", "故障位置", required=True),
            ScenarioParameter("operating_state", "故障前运行状态", required=True),
            ScenarioParameter("fault_current", "故障电流", "number", "A"),
            ScenarioParameter("protection_state", "保护动作状态"),
        ],
        operating_states=["正常运行", "故障检测", "保护动作", "故障隔离", "供电恢复", "闭锁"],
        trigger_events=["短路", "接地故障", "过流", "母线故障", "断路器失灵", "保护告警"],
        state_transitions=[
            StateTransition("正常运行", "检测到故障", "故障检测", "alarm"),
            StateTransition("故障检测", "保护判据满足", "保护动作", "trip"),
            StateTransition("保护动作", "故障设备已断开", "故障隔离", "isolate"),
            StateTransition("故障隔离", "恢复条件满足", "供电恢复", "restore_power"),
        ],
        protocol_capabilities=[
            ProtocolCapability("IEC61850", ("alarm", "trip", "isolate", "lockout", "close", "reset", "restore_power"), ("device_id", "logical_node", "data_object"), ("PTRC", "XCBR", "RREC", "RBRF")),
            ProtocolCapability("Modbus", ("alarm", "trip", "isolate", "lockout", "close", "reset"), ("device_id", "slave_id", "coil_address")),
        ],
        risk_controls=["故障位置和保护动作信息不完整时禁止生成操作载荷", "恢复供电前校验故障已隔离", "所有开关操作必须人工确认"],
    )

    @property
    def scenario_name(self) -> str:
        return self.definition.name
