from __future__ import annotations

from .models import ProtocolCapability, ScenarioDefinition, ScenarioParameter, StateTransition


class OffshoreWindScenario:
    definition = ScenarioDefinition(
        name="offshore_wind",
        aliases=["海上风电", "风电场", "集电线路", "风电机组"],
        required_parameters=["device_id", "operating_state"],
        allowed_actions=["trip", "close", "isolate", "alarm", "limit_power"],
        safety_level="high",
        standard_topics=["集电线路保护", "故障隔离", "并网", "功率限制"],
        device_types=["风电机组", "集电线路", "海上升压站", "断路器", "场站控制器"],
        parameters=[
            ScenarioParameter("device_id", "设备编号", required=True),
            ScenarioParameter("operating_state", "运行状态", required=True),
            ScenarioParameter("wind_speed", "风速", "number", "m/s"),
            ScenarioParameter("active_power", "有功功率", "number", "MW"),
            ScenarioParameter("collector_voltage", "集电线路电压", "number", "kV"),
        ],
        operating_states=["停运", "待机", "启动", "并网运行", "限功率运行", "故障", "检修"],
        trigger_events=["集电线路过流", "风机故障", "电压越限", "频率越限", "调度限功率指令"],
        state_transitions=[
            StateTransition("并网运行", "集电线路故障", "故障隔离", "trip"),
            StateTransition("并网运行", "调度限功率指令", "限功率运行", "limit_power"),
        ],
        protocol_capabilities=[
            ProtocolCapability("IEC61850", ("trip", "close", "isolate", "alarm", "limit_power"), ("device_id", "logical_node", "data_object"), ("XCBR", "CSWI", "MMXU")),
            ProtocolCapability("Modbus", ("trip", "close", "alarm", "limit_power"), ("device_id", "slave_id", "coil_address")),
        ],
        risk_controls=["保护动作和功率控制必须人工确认", "故障状态禁止自动重合闸", "保留动作时标与事件记录"],
    )

    @property
    def scenario_name(self) -> str:
        return self.definition.name
