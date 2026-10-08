from __future__ import annotations

from .models import ProtocolCapability, ScenarioDefinition, ScenarioParameter, StateTransition


class RenewableGridIntegrationScenario:
    definition = ScenarioDefinition(
        name="renewable_grid_integration",
        aliases=["新能源并网", "新能源场站并网", "光伏并网", "风电并网", "储能并网", "并网运行"],
        required_parameters=["plant_id", "generation_type", "connection_voltage", "operating_state"],
        allowed_actions=[
            "synchronize", "connect_grid", "disconnect_grid", "limit_power", "adjust_active_power",
            "adjust_reactive_power", "regulate_voltage", "alarm", "trip",
        ],
        safety_level="critical",
        standard_topics=["并网条件", "有功功率控制", "无功与电压控制", "频率响应", "低电压穿越", "电能质量"],
        device_types=["风电场", "光伏电站", "储能电站", "并网断路器", "逆变器", "场站控制器", "AGC", "AVC"],
        parameters=[
            ScenarioParameter("plant_id", "场站编号", required=True),
            ScenarioParameter("generation_type", "电源类型", required=True),
            ScenarioParameter("connection_voltage", "并网电压", "number", "kV", True),
            ScenarioParameter("operating_state", "运行状态", required=True),
            ScenarioParameter("frequency", "并网点频率", "number", "Hz"),
            ScenarioParameter("active_power", "有功功率", "number", "MW"),
            ScenarioParameter("reactive_power", "无功功率", "number", "Mvar"),
            ScenarioParameter("power_factor", "功率因数", "number"),
        ],
        operating_states=["停运", "待并网", "同期检查", "并网运行", "限功率运行", "故障穿越", "解列"],
        trigger_events=["并网申请", "同期条件满足", "调度功率指令", "电压越限", "频率越限", "故障穿越失败"],
        state_transitions=[
            StateTransition("待并网", "同期条件满足", "并网运行", "connect_grid"),
            StateTransition("并网运行", "调度限功率指令", "限功率运行", "limit_power"),
            StateTransition("并网运行", "保护解列条件满足", "解列", "disconnect_grid"),
        ],
        protocol_capabilities=[
            ProtocolCapability("IEC61850", ("synchronize", "connect_grid", "disconnect_grid", "limit_power", "adjust_active_power", "adjust_reactive_power", "regulate_voltage", "alarm", "trip"), ("device_id", "logical_node", "data_object"), ("CSWI", "XCBR", "MMXU", "GAPC")),
            ProtocolCapability("Modbus", ("connect_grid", "disconnect_grid", "limit_power", "adjust_active_power", "adjust_reactive_power", "regulate_voltage", "alarm"), ("device_id", "slave_id", "coil_address")),
        ],
        risk_controls=["并网前必须校验电压、频率和相位条件", "功率设定值必须校验上下限和变化率", "解列与并网操作必须人工确认"],
    )

    @property
    def scenario_name(self) -> str:
        return self.definition.name
