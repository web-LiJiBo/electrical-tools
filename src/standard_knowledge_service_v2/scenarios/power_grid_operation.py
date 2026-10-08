from __future__ import annotations

from .models import ProtocolCapability, ScenarioDefinition, ScenarioParameter, StateTransition


class PowerGridOperationScenario:
    definition = ScenarioDefinition(
        name="power_grid_operation",
        aliases=["电网调度运行", "电网调度", "调度运行", "调度控制", "运行方式调整", "负荷调度"],
        required_parameters=["control_area", "operating_state", "dispatch_target"],
        allowed_actions=[
            "issue_dispatch_order", "adjust_active_power", "adjust_reactive_power", "regulate_voltage",
            "start", "stop", "load_shedding", "restore_load", "alarm",
        ],
        safety_level="critical",
        standard_topics=["调度指令", "运行方式", "有功平衡", "无功电压", "频率控制", "负荷控制", "事故备用"],
        device_types=["发电机组", "变电站", "输电线路", "母线", "负荷", "储能电站", "场站控制器"],
        parameters=[
            ScenarioParameter("control_area", "控制区域", required=True),
            ScenarioParameter("operating_state", "电网运行状态", required=True),
            ScenarioParameter("dispatch_target", "调度对象", required=True),
            ScenarioParameter("frequency", "系统频率", "number", "Hz"),
            ScenarioParameter("target_active_power", "目标有功功率", "number", "MW"),
            ScenarioParameter("target_voltage", "目标电压", "number", "kV"),
            ScenarioParameter("reserve_capacity", "备用容量", "number", "MW"),
        ],
        operating_states=["正常", "警戒", "紧急", "恢复", "检修方式", "孤网运行"],
        trigger_events=["负荷预测偏差", "频率偏差", "电压越限", "设备停运", "断面越限", "事故备用调用"],
        state_transitions=[
            StateTransition("正常", "频率偏差", "警戒", "adjust_active_power"),
            StateTransition("警戒", "断面严重越限", "紧急", "load_shedding"),
            StateTransition("紧急", "系统稳定且备用恢复", "恢复", "restore_load"),
        ],
        protocol_capabilities=[
            ProtocolCapability("IEC61850", ("adjust_active_power", "adjust_reactive_power", "regulate_voltage", "start", "stop", "load_shedding", "restore_load", "alarm"), ("device_id", "logical_node", "data_object"), ("GAPC", "MMXU", "CSWI")),
            ProtocolCapability("Modbus", ("adjust_active_power", "adjust_reactive_power", "regulate_voltage", "start", "stop", "load_shedding", "restore_load", "alarm"), ("device_id", "slave_id", "coil_address")),
        ],
        risk_controls=["调度目标和设定值必须双重校核", "越限控制必须记录指令来源与时标", "控制指令必须由授权调度员确认"],
    )

    @property
    def scenario_name(self) -> str:
        return self.definition.name
